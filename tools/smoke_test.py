"""Phase 2 smoke test (spec section 2): time 50 abstracts and extrapolate.

Loads the tagger, tags a sample, reports throughput and the projected wall clock for
the whole untagged corpus, and halves tag_batch_size in config/tuning.toml on a Metal
allocation error. If the projection exceeds the compute budget the caller caps the
summary field, then drops tier 5, then moves to the Space: this script only measures.
"""
from __future__ import annotations

import argparse
import json
import time

import tomli_w

from pipeline import common as c
from pipeline import schema
from pipeline import tag as tag_module


def main() -> int:
    ap = argparse.ArgumentParser(description="Time the tagger on a sample")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--model", default=None)
    ap.add_argument("--adapter", default=None)
    args = ap.parse_args()

    conn = c.connect()
    tuning = c.tuning()
    rows = tag_module.pending(conn, args.n, None)
    if not rows:
        c.log("smoke: nothing untagged to measure")
        return 0
    total_untagged = len(tag_module.pending(conn, None, None))

    model_path = args.model or tuning.get("model_id", "Qwen/Qwen2.5-3B-Instruct")
    fused = c.ADAPTERS / "debris_v1_fused"
    q4 = c.ADAPTERS / "debris_v1_q4"
    if args.model is None:
        if q4.exists():
            model_path = str(q4)
        elif fused.exists():
            model_path = str(fused)

    c.log(f"smoke: loading {model_path}" + (f" + {args.adapter}" if args.adapter else ""))
    started = time.monotonic()
    try:
        tagger = tag_module.LocalTagger(model_path, args.adapter)
    except Exception as exc:
        c.log(f"smoke: load failed ({type(exc).__name__}: {exc})")
        return 2
    load_seconds = time.monotonic() - started

    valid = 0
    problems_seen: list[str] = []
    started = time.monotonic()
    for i, row in enumerate(rows, 1):
        try:
            greedy, sampled, raw = tagger.tag(dict(row))
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            c.log(f"smoke: generation failed on {row['pmid']} ({message})")
            if "allocat" in message.lower() or "metal" in message.lower():
                new_batch = max(1, int(tuning.get("tag_batch_size", 8)) // 2)
                tuning["tag_batch_size"] = new_batch
                tuning["tag_batch_size_status"] = f"halved by the smoke test ({message[:60]})"
                (c.CONFIG / "tuning.toml").write_text(tomli_w.dumps(tuning))
                c.log(f"smoke: halved tag_batch_size to {new_batch} after a Metal error")
            return 3
        tag, problems, _ = schema.validate(greedy)
        valid += 1 if tag is not None else 0
        problems_seen.extend(problems)
        if i % 10 == 0:
            rate = i / (time.monotonic() - started)
            print(f"  {i}/{len(rows)} at {rate * 60:.1f}/min", flush=True)

    elapsed = time.monotonic() - started
    per_paper = elapsed / len(rows)
    projection_hours = per_paper * total_untagged / 3600
    budget = float(tuning.get("max_compute_hours", 24))
    report = {
        "model": model_path, "n": len(rows), "load_seconds": round(load_seconds, 1),
        "seconds_per_paper": round(per_paper, 2),
        "papers_per_minute": round(60 / per_paper, 1),
        "valid_json_rate": round(valid / len(rows), 3),
        "untagged_corpus": total_untagged,
        "projected_hours": round(projection_hours, 2),
        "budget_hours": budget,
        "within_budget": projection_hours <= budget,
        "common_problems": sorted(set(problems_seen))[:8],
    }
    (c.ROOT / "data" / "smoke_test.json").write_text(json.dumps(report, indent=1))
    c.log("smoke: " + json.dumps(report))
    if not report["within_budget"]:
        c.log(f"smoke: projection {projection_hours:.1f} h exceeds the {budget} h budget; "
              f"cap the summary field, then drop tier 5, then tag on the Space")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
