"""HobbyLM-1B Instruct FP32 + Hobby LoRA on Apple MLX (KV cache), for speed. Same interface as torch_runtime.TorchHobby.

Weights: models/hobbylm-1B-instruct/model.safetensors (FP32 Instruct, sha256 d0899e0a…), loaded with the release's own MLX runtime
(HF layout adapter). The LoRA is added in memory as precomputed deltas (hobbymac-delta-<round>.npz, exported from the
verified adapter). No merged copy is written to disk. Greedy decoding; 1,024-token budget enforced.
"""
from __future__ import annotations

import os

import json
import sys
import time
from pathlib import Path

import mlx.core as mx
import numpy as np

ROOT = Path(os.environ.get('HOBBY_HOME', Path(__file__).resolve().parents[1]))  # repo root
FP32_DIR = ROOT / 'models' / 'hobbylm-1B-instruct'
REL = ROOT / 'models' / 'hobbylm-1B-mlx'
sys.path.insert(0, str(REL / 'runtime'))
from mlx_hobbylm.chat import generate, load_tokenizer  # noqa: E402
from mlx_hobbylm.model import HobbyLM, HobbyLMConfig  # noqa: E402
from mlx_hobbylm.weights import _adapt_weights  # noqa: E402

TOKEN_BUDGET = 1024


class MlxHobby:
    def __init__(self, delta: Path | None = None):
        cfg = HobbyLMConfig.from_dict(json.loads((FP32_DIR / 'config.json').read_text()))
        raw = mx.load(str(FP32_DIR / 'model.safetensors'))
        n = 0
        if delta:
            z = np.load(delta)
            if '__scale__' in z:  # compact low-rank file: weight += scale * B @ A (14 MB instead of 540 MB)
                sc = float(z['__scale__'])
                for k in [k[:-3] for k in z.files if k.endswith('::A')]:
                    raw[k] = raw[k] + (sc * (mx.array(z[k + '::B']) @ mx.array(z[k + '::A']))).astype(raw[k].dtype)
                    n += 1
            else:  # older pre-multiplied delta file
                for k, v in z.items():
                    raw[k] = raw[k] + mx.array(v).astype(raw[k].dtype)
                    n += 1
        self.model = HobbyLM(cfg)
        self.model.load_weights(list(_adapt_weights(raw, cfg).items()), strict=True)
        self.model.eval()
        mx.eval(self.model.parameters())
        self.tok = load_tokenizer(REL)
        self.identity = {'model.safetensors': 'd0899e0a… (hobbylm-1B-instruct, FP32)', 'delta': str(delta) if delta else None, 'deltas_applied': n,
                         'runtime': 'MLX via models/hobbylm-1B-mlx/runtime'}

    def complete(self, system: str, user: str, max_new: int = 48) -> dict:  # 48: EVENT lines need ~25-35 tokens (16 truncated them)
        ids = self.tok(f'SYSTEM: {system}\nUSER: {user}\nASSISTANT:').input_ids
        if len(ids) + max_new > TOKEN_BUDGET:
            raise ValueError(f'prompt {len(ids)} + output {max_new} exceeds {TOKEN_BUDGET}')
        t0 = time.perf_counter()
        out, _ = generate(self.model, ids, max_tokens=max_new, temperature=0.0, repetition_penalty=1.0, context=TOKEN_BUDGET,
                          eos_token_id=self.tok.eos_token_id, vocab_size=len(self.tok))
        out = [t for t in out if t != self.tok.eos_token_id]
        return {'prompt_tokens': len(ids), 'output_tokens': len(out), 'total_tokens': len(ids) + len(out),
                'seconds': time.perf_counter() - t0, 'raw': self.tok.decode(out)}
