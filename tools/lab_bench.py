"""How many lab jobs this GPU can run at once, measured rather than assumed (D36).

Run with the GPU otherwise idle. Every job runs under the memory cap it would get in the lab,
and four arrangements are timed: one training alone, two trainings together, one scoring
alone, and one training beside one scoring. The result goes into the [lab] table of
config/tuning.toml, which tools/hwprobe.py keeps across re-probes:

  parallel_jobs    2 only when two capped trainings together beat one alone by a quarter
  overlap_scoring  true only when scoring beside training slows the training by under a tenth

  pixi run python tools/lab_bench.py
  pixi run python tools/lab_bench.py --model Qwen/Qwen3-4B-Instruct-2507 --layers 36 \
      --grad-checkpoint --iters 60 --train-only --no-write     # a pair of 4B runs (D70)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import tomllib
from pathlib import Path

import tomli_w

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import common as c  # noqa: E402
from pipeline import lab  # noqa: E402
from pipeline.mlx_capped import caps_env  # noqa: E402

ITERS = 80
SCORE_PAPERS = 96
SOURCE = "phase0-baseline"      # fold 0 of the baseline supplies the data and a checkpoint
WORK = lab.LAB / "bench"
TUNING = c.ROOT / "config" / "tuning.toml"


def caps(jobs: int) -> dict:
    """The cap each job would run under with this many jobs sharing the GPU."""
    hw = tomllib.loads((c.ROOT / "config" / "hardware.toml").read_text())
    share = round(hw["gpu_working_set_gb"] * 0.9 / jobs, 1)
    return caps_env(share, round(share / 4, 1))


ARGS = argparse.Namespace(model="Qwen/Qwen2.5-1.5B-Instruct", layers=16, grad_checkpoint=False,
                          iters=ITERS, data=None)


def start_training(tag: str, jobs: int) -> subprocess.Popen:
    data = Path(ARGS.data) if ARGS.data else lab.unit_dir(SOURCE, 0, 42) / "data"
    out = WORK / tag
    out.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(c.ROOT / "pipeline" / "mlx_capped.py"), "mlx_lm.lora",
           "--model", ARGS.model, "--train", "--data", str(data),
           "--fine-tune-type", "lora", "--num-layers", str(ARGS.layers), "--batch-size", "4",
           "--iters", str(ARGS.iters), "--learning-rate", "1e-5", "--adapter-path", str(out),
           "--seed", "42", "--save-every", "100000", "--steps-per-eval", "100000",
           "--steps-per-report", "10", "--val-batches", "1", "--mask-prompt"]
    if ARGS.grad_checkpoint:
        cmd.append("--grad-checkpoint")
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "TOKENIZERS_PARALLELISM": "false",
           **caps(jobs)}
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, env=env)


def start_scoring(jobs: int) -> subprocess.Popen:
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "TOKENIZERS_PARALLELISM": "false",
           **caps(jobs)}
    return subprocess.Popen([sys.executable, __file__, "--score-worker"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)


def training_rate(output: str) -> dict:
    """Steady-state iterations a second, leaving out the first report's warm-up."""
    rates = [float(m.group(2)) for m in re.finditer(r"Iter (\d+): Train loss [\d.]+.*?It/sec ([\d.]+)", output)
             if int(m.group(1)) > min(20, ARGS.iters // 3)]
    peak = re.findall(r"Peak mem ([\d.]+) GB", output)
    return {"it_per_s": round(sum(rates) / len(rates), 3) if rates else None,
            "peak_gb": float(peak[-1]) if peak else None,
            "failed": "Insufficient Memory" in output or not rates}


def finish(procs: dict[str, subprocess.Popen]) -> dict[str, str]:
    return {tag: p.communicate()[0] for tag, p in procs.items()}


def score_worker() -> None:
    """Score a slice of fold 0 from the baseline's last checkpoint, under the caps the
    parent set, and print the rate."""
    from mlx_lm import load

    from pipeline.mlx_capped import apply_caps

    apply_caps()
    records = lab.canonical_records()
    folds = lab.assign_folds(records)
    held = sorted((r for r in records if folds[r["pmid"]] == 0), key=lambda r: r["pmid"])[:SCORE_PAPERS]
    cfg = lab.load_config(SOURCE)
    adapters = lab.unit_dir(SOURCE, 0, 42) / "adapters"
    model, tokenizer = load(cfg["model"], adapter_path=str(lab.checkpoint(adapters, cfg["iters"])))
    started = time.monotonic()
    lab.generate_batch(model, tokenizer, [lab.user_prompt(r["paper"], {}) for r in held])
    print(json.dumps({"s_per_paper": round((time.monotonic() - started) / len(held), 3)}))


def scoring_rate(output: str) -> dict:
    found = re.findall(r'\{"s_per_paper": ([\d.]+)\}', output)
    return {"s_per_paper": float(found[-1]) if found else None,
            "failed": "Insufficient Memory" in output or not found}


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--score-worker":
        score_worker()
        return 0
    ap = argparse.ArgumentParser(description="Measure how many lab jobs the GPU runs at once")
    ap.add_argument("--model", default=ARGS.model)
    ap.add_argument("--layers", type=int, default=ARGS.layers)
    ap.add_argument("--grad-checkpoint", action="store_true")
    ap.add_argument("--iters", type=int, default=ITERS)
    ap.add_argument("--data", default=None, help="a lab data dir (default: the Phase 0 baseline's)")
    ap.add_argument("--train-only", action="store_true", help="skip the scoring arrangements")
    ap.add_argument("--no-write", action="store_true", help="report only; leave tuning.toml alone")
    args = ap.parse_args()
    vars(ARGS).update(vars(args))
    adapters = lab.unit_dir(SOURCE, 0, 42) / "adapters"
    if not (adapters / f"{lab.load_config(SOURCE)['iters']:07d}_adapters.safetensors").exists():
        raise SystemExit("the Phase 0 baseline's fold 0 is not trained yet")
    WORK.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict] = {}

    c.log("lab bench: one training alone")
    results["train_alone"] = training_rate(finish({"a": start_training("alone", 2)})["a"])

    c.log("lab bench: two trainings together")
    out = finish({"a": start_training("pair-a", 2), "b": start_training("pair-b", 2)})
    pair = [training_rate(out["a"]), training_rate(out["b"])]
    results["train_pair"] = {"jobs": pair,
                             "it_per_s_total": round(sum(j["it_per_s"] or 0 for j in pair), 3),
                             "failed": any(j["failed"] for j in pair)}

    if args.train_only:
        alone = results["train_alone"]["it_per_s"] or 0
        total = results["train_pair"]["it_per_s_total"]
        c.log(f"lab bench ({args.model}, {args.layers} layers, grad checkpoint "
              f"{args.grad_checkpoint}): one training {alone} it/s, peak "
              f"{results['train_alone']['peak_gb']} GB; two together {total} it/s "
              f"({round(total / alone, 2) if alone else 0}x), peaks "
              f"{[j['peak_gb'] for j in results['train_pair']['jobs']]} GB")
        print(json.dumps(results, indent=1))
        return 0

    c.log("lab bench: one scoring alone")
    results["score_alone"] = scoring_rate(finish({"s": start_scoring(2)})["s"])

    c.log("lab bench: one training beside one scoring")
    out = finish({"t": start_training("overlap", 2), "s": start_scoring(2)})
    results["train_with_scoring"] = {"train": training_rate(out["t"]), "score": scoring_rate(out["s"])}

    alone = results["train_alone"]["it_per_s"] or 0
    pair_total = results["train_pair"]["it_per_s_total"]
    beside = results["train_with_scoring"]["train"]["it_per_s"] or 0
    speedup = round(pair_total / alone, 2) if alone else 0
    slowdown = round(1 - beside / alone, 3) if alone else 1
    failures = [k for k, v in results.items()
                if v.get("failed") or any(isinstance(x, dict) and x.get("failed") for x in v.values())]
    jobs = 2 if speedup >= 1.25 and not failures else 1
    overlap = slowdown < 0.10 and not failures

    if args.no_write:
        print(json.dumps(results, indent=1))
        return 0
    tuning = tomllib.loads(TUNING.read_text())
    lab_cfg = tuning.setdefault("lab", {})
    lab_cfg.update({"parallel_jobs": jobs, "overlap_scoring": overlap,
                    "parallel_jobs_status": f"measured {c.now()[:10]}: pair speedup {speedup}x, "
                                            f"training slowed {slowdown:.0%} beside scoring",
                    "bench": json.dumps(results, separators=(",", ":"))})
    share = round(tomllib.loads((c.ROOT / "config" / "hardware.toml").read_text())
                  ["gpu_working_set_gb"] * 0.9 / jobs, 1)
    lab_cfg["job_memory_gb"], lab_cfg["job_cache_gb"] = share, round(share / 4, 1)
    TUNING.write_text(tomli_w.dumps(tuning))
    c.log(f"lab bench: one training {alone} it/s; two together {pair_total} it/s "
          f"({speedup}x); training beside scoring {beside} it/s ({slowdown:.0%} slower); "
          f"scoring alone {results['score_alone']['s_per_paper']} s/paper, beside training "
          f"{results['train_with_scoring']['score']['s_per_paper']} s/paper; failures {failures or 'none'}. "
          f"parallel_jobs {jobs}, overlap_scoring {overlap}")
    print(json.dumps(results, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
