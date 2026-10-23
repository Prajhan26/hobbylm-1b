"""HobbyLM-1B Instruct FP32 (models/hobbylm-1B-instruct/, sha256 d0899e0a…) on MPS, optionally with a LoRA merged in.
Same interface as hobby_runtime.Hobby.complete(); native SYSTEM:/USER:/ASSISTANT: format; greedy; 1,024-token budget enforced.
"""
from __future__ import annotations

import os

import hashlib
import time
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, GPT2TokenizerFast

ROOT = Path(os.environ.get('HOBBY_HOME', Path(__file__).resolve().parents[1]))  # repo root
FP32_DIR = ROOT / 'models' / 'hobbylm-1B-instruct'
TOK_DIR = ROOT / 'models' / 'hobbylm-1B-mlx'
FP32_SHA = 'd0899e0ac88c90a2c01ca481463bc0f96c6d50337f1b3e0dc56e1d3dc2999e89'
TOKEN_BUDGET = 1024


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1 << 24), b''):
            h.update(c)
    return h.hexdigest()


class TorchHobby:
    def __init__(self, adapter: Path | None = None, adapter_sha: str | None = None, device: str = 'mps'):
        assert sha(FP32_DIR / 'model.safetensors') == FP32_SHA, 'FP32 weights changed'
        self.identity = {'model.safetensors': FP32_SHA, 'adapter': None}
        self.tok = GPT2TokenizerFast.from_pretrained(str(TOK_DIR), local_files_only=True)
        self.model = AutoModelForCausalLM.from_pretrained(str(FP32_DIR), trust_remote_code=True, torch_dtype=torch.float32).to(device).eval()
        self.device = device
        if adapter:
            got = sha(adapter)
            assert got == adapter_sha, 'adapter hash does not match the trained run'
            st = torch.load(adapter, map_location='cpu')
            scale = st['recipe']['lora']['alpha'] / st['recipe']['lora']['r']
            mods = dict(self.model.named_modules())
            n = 0
            with torch.no_grad():
                for k, a in st['lora'].items():
                    if '.lora_A.' in k:
                        name = k.split('.lora_A.')[0].removeprefix('base_model.model.')
                        b = st['lora'][k.replace('.lora_A.', '.lora_B.')]
                        mods[name].weight += (scale * (b @ a)).to(mods[name].weight.device)
                        n += 1
            self.identity['adapter'] = got
            self.identity['merged_modules'] = n

    def complete(self, system: str, user: str, max_new: int = 16, use_cache: bool = True) -> dict:
        ids = self.tok(f'SYSTEM: {system}\nUSER: {user}\nASSISTANT:').input_ids
        if len(ids) + max_new > TOKEN_BUDGET:
            raise ValueError(f'prompt {len(ids)} + output {max_new} exceeds {TOKEN_BUDGET}')
        out, t0 = [], time.perf_counter()
        with torch.inference_mode():
            if use_cache:  # greedy with KV cache: prompt once, then one token per step
                o = self.model(input_ids=torch.tensor([ids], device=self.device), use_cache=True)
                past, logits = o.past_key_values, o.logits[0, -1]
                for _ in range(max_new):
                    nxt = int(logits.argmax())
                    if nxt == self.tok.eos_token_id:
                        break
                    out.append(nxt)
                    o = self.model(input_ids=torch.tensor([[nxt]], device=self.device), past_key_values=past, use_cache=True)
                    past, logits = o.past_key_values, o.logits[0, -1]
            else:  # original path: recompute the whole sequence each step
                for _ in range(max_new):
                    nxt = int(self.model(input_ids=torch.tensor([ids + out], device=self.device)).logits[0, -1].argmax())
                    if nxt == self.tok.eos_token_id:
                        break
                    out.append(nxt)
        return {'prompt_tokens': len(ids), 'output_tokens': len(out), 'total_tokens': len(ids) + len(out),
                'seconds': time.perf_counter() - t0, 'raw': self.tok.decode(out)}
