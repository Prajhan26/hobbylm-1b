"""HobbyLM-1B Instruct (Apple MLX release) loaded through the release's own bundled runtime, unchanged.

Identity is checked against the release's SHA256SUMS before loading. The repository's top-level `mlx_hobbylm/`
has uncommitted local edits, so it is deliberately NOT used. Greedy decoding, no sampling, no prompt truncation:
a prompt that would push prompt+output past the budget raises instead of being cut.
"""
from __future__ import annotations

import os

import hashlib
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get('HOBBY_HOME', Path(__file__).resolve().parents[1]))  # repo root
MODEL_DIR = ROOT / 'models' / 'hobbylm-1B-mlx'
RUNTIME_DIR = MODEL_DIR / 'runtime'
MODEL_SHA256 = '18382d789b8348f17008b188482ec7b039e597a8d80161b023f2788f10c0a150'
TOKEN_BUDGET = 1024  # prompt + output, per call


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 24), b''):
            h.update(chunk)
    return h.hexdigest()


def verify_release(check_weights: bool = True) -> dict:
    sums = {}
    for line in (MODEL_DIR / 'SHA256SUMS.txt').read_text().splitlines():
        sha, rel = line.split(maxsplit=1)
        sums[rel.removeprefix('./')] = sha
    checked = {}
    for rel, sha in sums.items():
        if rel.startswith('validation/') or rel == 'README.md':
            continue
        if rel == 'model.safetensors' and not check_weights:
            continue
        got = _sha(MODEL_DIR / rel)
        if got != sha:
            raise SystemExit(f'Release file changed: {rel}')
        checked[rel] = got
    if check_weights:
        assert checked['model.safetensors'] == MODEL_SHA256
    return checked


class Hobby:
    def __init__(self, check_weights: bool = True):
        self.identity = verify_release(check_weights)
        sys.path.insert(0, str(RUNTIME_DIR))
        import mlx_hobbylm  # noqa: E402  (release runtime, verified above)
        from mlx_hobbylm.chat import generate, load_tokenizer
        from mlx_hobbylm.weights import load_local
        assert Path(mlx_hobbylm.__file__).resolve().is_relative_to(RUNTIME_DIR.resolve()), mlx_hobbylm.__file__
        self._generate = generate
        t0 = time.perf_counter()
        self.model, self.cfg = load_local(MODEL_DIR)
        self.tok = load_tokenizer(MODEL_DIR)
        self.load_seconds = time.perf_counter() - t0

    def prompt_ids(self, messages: list[dict], fmt: str) -> list[int]:
        if fmt == 'released':  # tokenizer's shipped <|role|> template
            return list(self.tok.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, return_dict=True)['input_ids'])
        if fmt == 'native':  # literal training formatter (docs/HOBBYLM_INFERENCE_AUDIT_2026-10-14.md)
            parts = [f"{m['role'].upper()}: {m['content']}" for m in messages]
            return self.tok('\n'.join(parts) + '\nASSISTANT:').input_ids
        raise ValueError(fmt)

    def complete(self, messages: list[dict], fmt: str, max_new: int) -> dict:
        ids = self.prompt_ids(messages, fmt)
        if len(ids) + max_new > TOKEN_BUDGET:
            raise ValueError(f'prompt {len(ids)} + output {max_new} tokens exceeds the {TOKEN_BUDGET}-token budget')
        t0 = time.perf_counter()
        out, _ = self._generate(self.model, ids, max_tokens=max_new, temperature=0.0, repetition_penalty=1.0,
                                context=TOKEN_BUDGET, eos_token_id=self.tok.eos_token_id, vocab_size=len(self.tok))
        dt = time.perf_counter() - t0
        text = self.tok.decode([t for t in out if t != self.tok.eos_token_id], skip_special_tokens=True)
        return {'prompt_tokens': len(ids), 'output_tokens': len(out), 'total_tokens': len(ids) + len(out),
                'hit_max_new': len(out) >= max_new and (not out or out[-1] != self.tok.eos_token_id),
                'seconds': dt, 'raw': text}
