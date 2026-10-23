"""Fine-tune HobbyLM-1B Instruct (LoRA) on synthetic Hobby Mac helper decisions, on a Modal H100.

Run: modal run hobby/hobbymac_modal.py
Local: build the synthetic set, drop items resembling ANY test request (sealed Grok set + the earlier 34 Calculator
requests), freeze. Remote: verify weights, train LoRA, report synthetic dev accuracy, save the adapter to the volume.
The sealed test set is never sent to Modal; it is scored locally afterwards.
"""
import hashlib
import json
import random
import sys
from pathlib import Path

import modal

sys.path.insert(0, str(Path(__file__).parent))
_here = Path(__file__).resolve()
ROOT = _here.parents[1] if len(_here.parents) > 1 else Path('/root')  # on Modal the file sits at /root/
WORK = ROOT / 'data'
ROUND = 'r4'
FROZEN, RESULTS = WORK / 'frozen' / f'hobbymac-train-frozen-{ROUND}.json', WORK / f'hobbymac-train-results-{ROUND}.json'
SEALED = WORK / 'frozen' / f'hobbymac-sealed-test-{ROUND}.tsv'
REPO, REV = 'harims95/hobbylm-1B-instruct', '8a90f6eb6a3d7c7eb952fd01b512a406821366ab'
WEIGHT_SHA = 'd0899e0ac88c90a2c01ca481463bc0f96c6d50337f1b3e0dc56e1d3dc2999e89'
image = modal.Image.debian_slim(python_version='3.11').pip_install('torch==2.5.1', 'transformers==4.46.3', 'peft==0.13.2', 'huggingface_hub==0.26.2', 'safetensors', 'numpy<2')
app = modal.App('hobbylm-hobbymac', image=image)
cache = modal.Volume.from_name('hf-cache')


def build():
    import hobbymac_data as HD
    from hobbymac_data import SYSTEM_V2 as SYSTEM, filter_against, make
    HD.NEAR_SHARE = .3  # round 3: fewer near-miss refusals
    for p in (FROZEN, RESULTS):
        if p.exists():
            raise SystemExit(f'Preserve previous run: {p} exists')
    sealed = SEALED
    tests = [l.split('\t')[2] for l in sealed.read_text().splitlines() if l.strip()]
    old = json.loads((WORK / 'frozen' / 'calc-tasks.json').read_text())
    tests += [q for q, _ in old['dev']] + [q for xs in old['held_out'].values() for q, _ in xs]
    ex, dropped = filter_against(make(n_event=1800, n_none=800), tests)
    rng = random.Random(3)
    rng.shuffle(ex)
    dev, train = ex[:150], ex[150:]
    frozen = {'repo': REPO, 'revision': REV, 'system': SYSTEM, 'format': 'native SYSTEM:/USER:/ASSISTANT: (zero-shot)',
              'train': [(u, a) for _, _, u, a in train], 'dev': [(u, a) for _, _, u, a in dev],
              'counts': {'generated': len(ex) + len(dropped), 'dropped_resembling_tests': len(dropped), 'train': len(train), 'dev': len(dev),
                         'kinds': {k: sum(e[0] == k for e in train) for k in ('calc', 'device', 'none')}},
              'dropped_examples': dropped[:40], 'sealed_test_sha256': hashlib.sha256(sealed.read_bytes()).hexdigest(),
              'sealed_test_sent_to_modal': False,
              'recipe': {'lora': {'r': 16, 'alpha': 32, 'dropout': .05, 'targets': ['q_proj', 'k_proj', 'v_proj', 'o_proj', 'gate_proj', 'up_proj', 'down_proj']},
                         'epochs': 2, 'batch': 16, 'lr': 2e-4, 'loss': 'assistant action tokens + EOS only', 'router': 'frozen, bias updates off', 'seed': 3}}
    raw = (json.dumps(frozen, indent=1, ensure_ascii=False) + '\n').encode()
    FROZEN.write_bytes(raw)
    return frozen, hashlib.sha256(raw).hexdigest()


@app.function(gpu='H100', volumes={'/cache': cache}, timeout=3600)
def train(frozen: dict):
    import math, os, time
    import torch
    from huggingface_hub import snapshot_download
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer
    t0 = time.time(); torch.manual_seed(3); torch.backends.cuda.matmul.allow_tf32 = True
    path = snapshot_download(REPO, revision=REV, cache_dir='/cache/hub')
    h = hashlib.sha256()
    with open(f'{path}/model.safetensors', 'rb') as f:
        for c in iter(lambda: f.read(1 << 24), b''):
            h.update(c)
    assert h.hexdigest() == WEIGHT_SHA, 'weight hash mismatch'
    tok = AutoTokenizer.from_pretrained(path)
    model = AutoModelForCausalLM.from_pretrained(path, trust_remote_code=True, torch_dtype=torch.float32).cuda()
    for m in model.modules():
        if hasattr(m, 'bias_update_rate'):
            m.bias_update_rate = 0.0
    sysmsg = frozen['system']

    def encode(u, a):
        p = tok(f'SYSTEM: {sysmsg}\nUSER: {u}\nASSISTANT:').input_ids
        t = tok(' ' + a).input_ids + [tok.eos_token_id]
        return p, t

    @torch.inference_mode()
    def greedy(u, n=48):  # 48: EVENT lines are longer (16 truncated them in round 3)
        ids = encode(u, '')[0]
        out = []
        for _ in range(n):
            nxt = int(model(input_ids=torch.tensor([ids + out]).cuda()).logits[0, -1].argmax())
            if nxt == tok.eos_token_id:
                break
            out.append(nxt)
        return tok.decode(out).strip()

    def dev_acc():
        model.eval()
        return sum(greedy(u) == a for u, a in frozen['dev']) / len(frozen['dev'])

    before = dev_acc(); print('dev before', before, flush=True)
    rc = frozen['recipe']['lora']
    model = get_peft_model(model, LoraConfig(r=rc['r'], lora_alpha=rc['alpha'], lora_dropout=rc['dropout'], target_modules=rc['targets'], task_type='CAUSAL_LM'))
    data = [encode(u, a) for u, a in frozen['train']]
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=frozen['recipe']['lr'], weight_decay=0.0)
    bs, epochs = frozen['recipe']['batch'], frozen['recipe']['epochs']
    steps = epochs * math.ceil(len(data) / bs); warm = 20
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: (s + 1) / warm if s < warm else .5 * (1 + math.cos(math.pi * (s - warm) / max(1, steps - warm))))
    rng = random.Random(3); log = []; step = 0
    for ep in range(epochs):
        order = list(range(len(data))); rng.shuffle(order)
        model.train()
        for i in range(0, len(order), bs):
            batch = [data[j] for j in order[i:i + bs]]
            L = max(len(p) + len(t) for p, t in batch)
            ids = torch.full((len(batch), L), tok.eos_token_id); lab = torch.full((len(batch), L), -100); att = torch.zeros(len(batch), L, dtype=torch.long)
            for r, (p, t) in enumerate(batch):
                s = p + t
                ids[r, :len(s)] = torch.tensor(s); att[r, :len(s)] = 1; lab[r, len(p):len(s)] = torch.tensor(t)
            out = model(input_ids=ids.cuda(), attention_mask=att.cuda())
            logits = out.logits[:, :-1].float(); tgt = lab[:, 1:].cuda()
            loss = torch.nn.functional.cross_entropy(logits.reshape(-1, logits.size(-1)), tgt.reshape(-1), ignore_index=-100)
            opt.zero_grad(); loss.backward(); torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0)
            opt.step(); sched.step(); step += 1
            if step % 25 == 0 or step == steps:
                log.append({'step': step, 'loss': float(loss)}); print('step', step, 'loss', round(float(loss), 4), flush=True)
    after = dev_acc(); print('dev after', after, flush=True)
    sd = {k: v.detach().cpu() for k, v in model.state_dict().items() if 'lora_' in k}
    os.makedirs('/cache/hobbymac', exist_ok=True)
    torch.save({'lora': sd, 'recipe': frozen['recipe'], 'revision': REV, 'weight_sha256': WEIGHT_SHA}, f'/cache/hobbymac/hobbymac-lora-{ROUND}.pt')
    sha = hashlib.sha256(open(f'/cache/hobbymac/hobbymac-lora-{ROUND}.pt', 'rb').read()).hexdigest()
    res = {'synthetic_dev': {'before': before, 'after': after, 'n': len(frozen['dev'])}, 'loss_log': log, 'adapter': f'hf-cache:/hobbymac/hobbymac-lora-{ROUND}.pt',
           'adapter_sha256': sha, 'gpu': 'H100', 'gpu_seconds': time.time() - t0, 'torch': str(torch.__version__)}
    json.dump(res, open(f'/cache/hobbymac/result-{ROUND}.json', 'w')); cache.commit()
    return json.loads(json.dumps(res))


@app.local_entrypoint()
def main():
    if FROZEN.exists() and not RESULTS.exists():  # reuse the training set frozen by an earlier attempt that crashed before training
        raw = FROZEN.read_bytes()
        frozen, sha = json.loads(raw), hashlib.sha256(raw).hexdigest()
        sealed = SEALED
        assert frozen['sealed_test_sha256'] == hashlib.sha256(sealed.read_bytes()).hexdigest(), 'sealed test changed'
        print('REUSING frozen training set', sha[:12], flush=True)
    else:
        frozen, sha = build()
    print('FROZEN', json.dumps(frozen['counts']), flush=True)
    out = train.remote(frozen)
    RESULTS.write_text(json.dumps({'frozen_sha256': sha, **out}, indent=1) + '\n')
    print('RESULT', json.dumps(out['synthetic_dev']), 'gpu min', round(out['gpu_seconds'] / 60, 1), flush=True)
