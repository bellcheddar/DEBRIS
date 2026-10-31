"""The encoder arm (D63): BioClinical-ModernBERT as a multi-label classifier for the
tagger's fixed-vocabulary fields, trained on the same papers as the 3B with enrichment
(phase5-enrich-b) and scored on the same frozen test split.

One shared encoder, one head per field: sigmoid heads for the list fields and the two
yes/no fields, softmax heads for size class and study type. Thresholds are tuned per field
on a validation slice of the training papers; the test split is read once, at the end.
The free-text fields (summary, disease terms) are left empty: no metric reads them.

  pixi run -e encoder python pipeline/encoder.py              # train, predict, write
  pixi run lab run encoder-mbert && pixi run lab report        # score against debris_v2

Writes data/lab/encoder/predictions.jsonl, which config/lab/encoder-mbert.toml imports.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import common as c  # noqa: E402
from pipeline import schema  # noqa: E402

HOME = c.DATA / "lab" / "encoder"
TRAIN_ROWS = c.DATA / "lab" / "phase5-enrich-b" / "f0-s42" / "data" / "train.jsonl"
MULTI = ["polymers", "organ_systems", "tissues", "disease_categories", "pathways", "evidence_rungs"]
SINGLE = ["size_class", "model_type"]
BINARY = ["relevant", "pet_specific"]
MIN_LABEL = 3   # an other:<name> label seen fewer times than this is not learnable


def load_training() -> list[tuple[str, dict]]:
    rows = []
    for row in c.jsonl_read(TRAIN_ROWS):
        msgs = {m["role"]: m["content"] for m in row["messages"]}
        rows.append((msgs["user"], json.loads(msgs["assistant"])))
    return rows


def label_space(rows: list[tuple[str, dict]]) -> dict[str, list]:
    from collections import Counter
    space = {}
    for f in MULTI:
        counts = Counter(str(v) for _, t in rows for v in t.get(f, []))
        space[f] = sorted(k for k, n in counts.items() if n >= MIN_LABEL)
    for f in SINGLE:
        space[f] = sorted({str(t.get(f)) for _, t in rows})
    return space


def targets(tag: dict, space: dict) -> dict:
    out = {f: [1.0 if lab in {str(v) for v in tag.get(f, [])} else 0.0 for lab in space[f]] for f in MULTI}
    out.update({f: space[f].index(str(tag.get(f))) for f in SINGLE})
    out.update({f: 1.0 if tag.get(f) else 0.0 for f in BINARY})
    return out


def build_model(name: str, space: dict):
    import torch
    from transformers import AutoModel

    class Tagger(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.encoder = AutoModel.from_pretrained(name)
            h = self.encoder.config.hidden_size
            self.drop = torch.nn.Dropout(0.1)
            self.heads = torch.nn.ModuleDict(
                {f: torch.nn.Linear(h, len(space[f])) for f in MULTI + SINGLE}
                | {f: torch.nn.Linear(h, 1) for f in BINARY})

        def forward(self, ids, mask):
            hidden = self.encoder(input_ids=ids, attention_mask=mask).last_hidden_state
            m = mask.unsqueeze(-1).to(hidden.dtype)
            pooled = self.drop((hidden * m).sum(1) / m.sum(1).clamp(min=1))   # mean pooling
            return {f: head(pooled) for f, head in self.heads.items()}

    return Tagger()


def loss_of(out, batch, torch):
    bce = torch.nn.functional.binary_cross_entropy_with_logits
    ce = torch.nn.functional.cross_entropy
    total = 0.0
    for f in MULTI:
        if out[f].shape[-1]:
            total = total + bce(out[f], batch[f])
    for f in SINGLE:
        total = total + ce(out[f], batch[f])
    for f in BINARY:
        total = total + bce(out[f].squeeze(-1), batch[f])
    return total


def batches(items, size, tok, max_len, space, torch, device, shuffle=False, seed=0):
    order = list(range(len(items)))
    if shuffle:
        random.Random(seed).shuffle(order)
    for start in range(0, len(order), size):
        chunk = [items[i] for i in order[start:start + size]]
        enc = tok([t for t, _ in chunk], truncation=True, max_length=max_len, padding=True,
                  return_tensors="pt")
        batch = {"ids": enc["input_ids"].to(device), "mask": enc["attention_mask"].to(device)}
        if chunk[0][1] is not None:
            tg = [targets(tag, space) for _, tag in chunk]
            for f in MULTI + BINARY:
                batch[f] = torch.tensor([t[f] for t in tg], dtype=torch.float32, device=device)
            for f in SINGLE:
                batch[f] = torch.tensor([t[f] for t in tg], dtype=torch.long, device=device)
        yield batch


def predict_probs(model, items, tok, max_len, space, torch, device, size=16) -> list[dict]:
    model.eval()
    out = []
    with torch.no_grad():
        for batch in batches(items, size, tok, max_len, space, torch, device):
            logits = model(batch["ids"], batch["mask"])
            probs = {f: (torch.sigmoid(logits[f]) if f in MULTI else torch.softmax(logits[f], -1)
                         if f in SINGLE else torch.sigmoid(logits[f].squeeze(-1))).cpu().tolist()
                     for f in logits}
            for i in range(batch["ids"].shape[0]):
                out.append({f: probs[f][i] for f in probs})
    return out


def decode(p: dict, space: dict, thr: dict) -> dict:
    """Probabilities to a tag in the schema, with the schema's own consistency rules."""
    tag = {"relevant": p["relevant"] >= thr["relevant"], "pet_specific": p["pet_specific"] >= thr["pet_specific"]}
    for f in SINGLE:
        tag[f] = space[f][max(range(len(p[f])), key=lambda i: p[f][i])]
    for f in MULTI:
        tag[f] = [lab for lab, q in zip(space[f], p[f]) if q >= thr[f]]
    tag["evidence_rungs"] = sorted(int(r) for r in tag["evidence_rungs"])
    tag["disease_categories"] = [d for d in tag["disease_categories"] if d != "none"] or ["none"]
    if not tag["relevant"]:
        tag.update({f: [] for f in MULTI}, disease_categories=["none"], model_type="not_applicable",
                   pet_specific=False, size_class="unspecified")
    elif tag["model_type"] == "not_applicable":
        # A relevant paper always has a study type: take the likeliest real one.
        ranked = sorted(range(len(p["model_type"])), key=lambda i: -p["model_type"][i])
        tag["model_type"] = next(space["model_type"][i] for i in ranked
                                 if space["model_type"][i] != "not_applicable")
    tag.update(summary="", disease_terms=[], confidence=0.9)
    return tag


def tune_thresholds(probs, tags, space) -> dict:
    """Per field, the threshold that maximises micro F1 (F1 for the yes/no fields) on the
    validation papers."""
    grid = [x / 20 for x in range(2, 17)]
    thr = {}
    for f in MULTI + BINARY:
        best = (-1.0, 0.5)
        for t in grid:
            tp = fp = fn = 0
            for p, g in zip(probs, tags):
                if f in BINARY:
                    pred, gold = p[f] >= t, bool(g.get(f))
                    tp += pred and gold; fp += pred and not gold; fn += gold and not pred
                else:
                    ps = {lab for lab, q in zip(space[f], p[f]) if q >= t}
                    gs = {str(v) for v in g.get(f, [])}
                    tp += len(ps & gs); fp += len(ps - gs); fn += len(gs - ps)
            f1 = 2 * tp / max(1, 2 * tp + fp + fn)
            if f1 > best[0]:
                best = (f1, t)
        thr[f] = best[1]
    return thr


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="thomas-sounack/BioClinical-ModernBERT-base")
    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--max-len", type=int, default=1024)
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--valid", type=int, default=164, help="training papers held back for thresholds")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    import torch
    from transformers import AutoTokenizer, get_linear_schedule_with_warmup

    torch.manual_seed(args.seed)
    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    rows = load_training()
    random.Random(args.seed).shuffle(rows)
    valid, train = rows[:args.valid], rows[args.valid:]
    space = label_space(train)
    tok = AutoTokenizer.from_pretrained(args.model)
    model = build_model(args.model, space).to(device)
    head_params = [p for n, p in model.named_parameters() if not n.startswith("encoder.")]
    enc_params = [p for n, p in model.named_parameters() if n.startswith("encoder.")]
    opt = torch.optim.AdamW([{"params": enc_params, "lr": args.lr},
                             {"params": head_params, "lr": args.lr * 20}], weight_decay=0.01)
    steps = args.epochs * math.ceil(len(train) / args.batch)
    sched = get_linear_schedule_with_warmup(opt, int(0.06 * steps), steps)
    HOME.mkdir(parents=True, exist_ok=True)
    log = (HOME / "train.log").open("w")
    best, best_state, started = float("inf"), None, time.monotonic()
    for epoch in range(args.epochs):
        model.train()
        total = n = 0
        for batch in batches(train, args.batch, tok, args.max_len, space, torch, device, True, args.seed + epoch):
            loss = loss_of(model(batch["ids"], batch["mask"]), batch, torch)
            opt.zero_grad(); loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); sched.step()
            total += loss.item(); n += 1
        model.eval()
        vtotal = vn = 0
        with torch.no_grad():
            for batch in batches(valid, 16, tok, args.max_len, space, torch, device):
                vtotal += loss_of(model(batch["ids"], batch["mask"]), batch, torch).item(); vn += 1
        line = (f"epoch {epoch + 1}: train loss {total / n:.4f}, val loss {vtotal / vn:.4f}, "
                f"{(time.monotonic() - started) / 60:.1f} min")
        print(line, flush=True); log.write(line + "\n"); log.flush()
        if vtotal / vn < best:
            best = vtotal / vn
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)
    vprobs = predict_probs(model, [(t, None) for t, _ in valid], tok, args.max_len, space, torch, device)
    thr = tune_thresholds(vprobs, [g for _, g in valid], space)

    test = list(c.jsonl_read(c.TRAIN / "test_meta.jsonl"))
    tprobs = predict_probs(model, [(schema.user_prompt(r["paper"]), None) for r in test],
                           tok, args.max_len, space, torch, device)
    c.jsonl_write(HOME / "predictions.jsonl",
                  [{"pmid": r["pmid"], "pred": decode(p, space, thr), "parsed": True, "problems": []}
                   for r, p in zip(test, tprobs)])
    (HOME / "run.json").write_text(json.dumps({
        "model": args.model, "epochs": args.epochs, "batch": args.batch, "max_len": args.max_len,
        "lr": args.lr, "train_papers": len(train), "valid_papers": len(valid),
        "best_val_loss": round(best, 4), "thresholds": thr,
        "labels": {f: len(v) for f, v in space.items()},
        "minutes": round((time.monotonic() - started) / 60, 1)}, indent=1))
    c.log(f"encoder: {args.model} trained on {len(train)} papers in "
          f"{(time.monotonic() - started) / 60:.1f} min; {len(test)} test papers predicted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
