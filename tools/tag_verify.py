"""Check the batched tagger against the old loop on labelled papers, then set [tag].

tools/tag_bench.py showed where the time goes but compared answers on 16 papers, which
cannot tell a batch's rounding apart from a change in quality (D45). This scores both on
the 162 test papers against their gold labels instead, paired paper by paper:

  old       pipeline/tag.py's previous loop, one paper at a time, greedy
  new-B     generate_many at batch B, the shared system-prompt cache on
  fused     the unquantised fused weights at the largest batch, whose prompt reading may
            be faster than 4-bit's
  hybrid    BatchedTagger.tag_many at the chosen batch: greedy, token probability, and the
            sampled pass for the least confident third, the full cost per paper (D45)

A new arm is equivalent when no floor metric's paired 95 % interval lies wholly below
zero, the lab's own guardrail rule. The fastest equivalent arm goes into [tag] in
config/tuning.toml. The test papers only check that faster code tags as well as the code
that produced the published test numbers; nothing here chooses a model.

  pixi run python tools/tag_verify.py      # needs the GPU to itself, about 30 minutes
"""
from __future__ import annotations

import json
import sys
import time
import tomllib
from pathlib import Path

import tomli_w

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import common as c  # noqa: E402
from pipeline import lab  # noqa: E402
from pipeline import schema  # noqa: E402
from pipeline import tag as T  # noqa: E402
from pipeline import train as production  # noqa: E402

BATCHES = (8, 16, 32)
TUNING = c.ROOT / "config" / "tuning.toml"
OUT = c.DATA / "manifests" / "tag_verify.json"


def rows_from(papers: list[dict], texts: list[str]) -> dict[str, dict]:
    out = {}
    for p, text in zip(papers, texts):
        raw = schema.extract_json(text)
        pred, _, _ = schema.validate(raw)
        out[p["pmid"]] = {"pmid": p["pmid"], "gold": p["tag"], "parsed": raw is not None,
                          "pred": pred if pred is not None else dict(production.UNPARSED)}
    return out


def versus(old: dict, new: dict) -> dict:
    eff = lab.bootstrap(lab.aligned_rows([old, new]),
                        lambda m: {k: m[1][k] - m[0][k] for k in lab.METRICS})
    harmed = [k for k in lab.FLOOR if eff[k][2] < 0]
    return {"effects": {k: [round(x, 4) for x in v] for k, v in eff.items()},
            "harmed": harmed, "equivalent": not harmed}


def main() -> int:
    from mlx_lm import load

    from tools.tag_bench import gpu_busy
    if busy := gpu_busy():
        raise SystemExit(f"the GPU is in use ({busy}); run with it idle")
    test = list(c.jsonl_read(c.TRAIN / "test_meta.jsonl"))
    papers = [dict(r["paper"], pmid=r["pmid"], tag=r["tag"]) for r in test]
    prompts = [schema.user_prompt(p) for p in papers]
    tuning = c.tuning()
    weights, adapter = T.local_model_choice(None, None, tuning)
    corpus = c.connect(readonly=True).execute(
        "SELECT count(*) FROM papers WHERE doi_status = 'verified' AND abstract <> ''").fetchone()[0]
    c.log(f"tag verify: {len(papers)} test papers, {weights}")
    tagger = T.LocalTagger(weights, adapter)
    result: dict = {"measured": c.now(), "papers": len(papers), "corpus": corpus, "weights": weights}

    started = time.monotonic()
    old_texts = [tagger.generate(p, 0.0) for p in prompts]
    old = rows_from(papers, old_texts)
    result["old"] = {"s_per_paper": round((time.monotonic() - started) / len(papers), 3)}
    c.log(f"tag verify: old loop {result['old']}")

    arms = {}
    for b in BATCHES:
        started = time.monotonic()
        texts = [t for t, _ in T.generate_many(tagger.model, tagger.tokenizer, prompts, b)]
        arms[f"new-{b}"] = {"s_per_paper": round((time.monotonic() - started) / len(papers), 3),
                            **versus(old, rows_from(papers, texts))}
        c.log(f"tag verify: new-{b} {arms[f'new-{b}']['s_per_paper']} s/paper, "
              f"equivalent {arms[f'new-{b}']['equivalent']} {arms[f'new-{b}']['harmed']}")
    equivalent = {k: v for k, v in arms.items() if v["equivalent"]}
    best = min(equivalent, key=lambda k: equivalent[k]["s_per_paper"]) if equivalent else None
    result["arms"] = arms

    if best:
        b = int(best.split("-")[1])
        batched = T.BatchedTagger.__new__(T.BatchedTagger)
        batched.model, batched.tokenizer, batched.name = tagger.model, tagger.tokenizer, tagger.name
        batched.batch, batched.prefix = b, True
        batched.fraction = float(tuning.get("tag", {}).get("sampled_fraction", 0.33))
        started = time.monotonic()
        out = batched.tag_many(papers)
        hybrid_s = round((time.monotonic() - started) / len(papers), 3)
        result["hybrid"] = {"batch": b, "s_per_paper": hybrid_s,
                            "sampled": sum(r["sampled_run"] for r in out),
                            "projected_hours": round(corpus * hybrid_s / 3600, 1)}
        c.log(f"tag verify: hybrid at batch {b} {result['hybrid']}")

    fused = c.ADAPTERS / "debris_v1_fused"
    if fused.exists() and weights != str(fused):
        del tagger
        model, tokenizer = load(str(fused))
        b = max(BATCHES)
        started = time.monotonic()
        texts = [t for t, _ in T.generate_many(model, tokenizer, prompts, b)]
        result["fused"] = {"batch": b, "s_per_paper": round((time.monotonic() - started) / len(papers), 3),
                           **versus(old, rows_from(papers, texts))}
        c.log(f"tag verify: fused at batch {b} {result['fused']['s_per_paper']} s/paper, "
              f"equivalent {result['fused']['equivalent']}")

    OUT.write_text(json.dumps(result, indent=1))
    if best:
        doc = tomllib.loads(TUNING.read_text())
        tag_cfg = doc.setdefault("tag", {})
        tag_cfg.update({"batch_size": int(best.split("-")[1]), "prefix_cache": True,
                        "s_per_paper": result["hybrid"]["s_per_paper"],
                        "status": f"verified against gold {c.now()[:10]} by tools/tag_verify.py, "
                                  f"see {OUT.relative_to(c.ROOT)}"})
        tag_cfg.pop("projected_hours", None)
        tag_cfg["projected_hours_hybrid"] = result["hybrid"]["projected_hours"]
        doc["tag_batch_size"] = tag_cfg["batch_size"]
        doc["tag_batch_size_status"] = tag_cfg["status"]
        TUNING.write_text(tomli_w.dumps(doc))
        c.log(f"tag verify: [tag] set to batch {tag_cfg['batch_size']} with the shared prompt; "
              f"a hybrid pass over {corpus} papers ~{result['hybrid']['projected_hours']} h")
    else:
        c.log("tag verify: no batched arm was equivalent to the old loop; [tag] left alone")
    print(json.dumps(result, indent=1))
    return 0 if best else 2


if __name__ == "__main__":
    raise SystemExit(main())
