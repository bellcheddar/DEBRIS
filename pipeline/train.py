"""The one-time LoRA fine-tune of the DEBRIS tagger (spec 5.5).

mlx-lm LoRA, then fuse (de-quantised, so transformers can load it on the Space) and
a q4 copy for Studio-side inference. Wrapper adapted from chatMCD's train scripts
(see REUSE.md). The adapter is trained once: the weekly pipeline never retrains.

  pixi run train              # train, fuse, convert, then score the test split
  pixi run train --score-only # re-score an existing adapter
  pixi run train --retrain    # start the fine-tune again from the base model

Each stage checks for its own output first, so an interrupted run resumes where it
stopped instead of repeating the fine-tune.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from pipeline import common as c
from pipeline import schema

ADAPTER = c.ADAPTERS / "debris_v1"
FUSED = c.ADAPTERS / "debris_v1_fused"
Q4 = c.ADAPTERS / "debris_v1_q4"

# Acceptance floor (spec 5.5).
FLOOR = {"relevant_f1": 0.95, "polymers_f1": 0.85, "organ_systems_f1": 0.85,
         "pathways_f1": 0.75, "rungs_exact": 0.70, "rungs_within_one": 0.90,
         "model_type_accuracy": 0.90, "valid_json": 0.98}


def run(cmd: list[str], log_path: Path | None = None, extra_env: dict | None = None) -> str:
    c.log("train: " + " ".join(cmd[:6]) + (" ..." if len(cmd) > 6 else ""))
    env = dict(os.environ, TOKENIZERS_PARALLELISM="false", **(extra_env or {}))
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    output = proc.stdout + proc.stderr
    if log_path:
        log_path.write_text(output)
    if proc.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed ({proc.returncode}): {output[-2000:]}")
    return output


def lora_report_args(project: str) -> list[str]:
    """mlx-lm's own live reporting, in whichever spelling this version offers.

    0.29.1 calls it `--report-to wandb` with a separate `--project-name`. Checking for a
    `--wandb` flag that does not exist meant the fine-tune streamed nothing and only the
    curve replayed afterwards reached wandb at all (D28).
    """
    try:
        helptext = subprocess.run(["mlx_lm.lora", "--help"], capture_output=True, text=True).stdout
    except FileNotFoundError:
        return []
    if "--report-to" in helptext:
        args = ["--report-to", "wandb"]
        if "--project-name" in helptext:
            args += ["--project-name", project]
        return args
    if "--wandb" in helptext:
        return ["--wandb", project]
    return []


def model_depth(model_id: str) -> int | None:
    """How many transformer layers the base model has, from its own config.

    Depth does not follow parameter count: Qwen2.5-3B has 36 layers and the 7B has 28,
    so a layer count that suits one model is rejected outright by the other.
    """
    try:
        from huggingface_hub import hf_hub_download
        cfg = json.loads(Path(hf_hub_download(model_id, "config.json")).read_text())
    except Exception as exc:  # no network and nothing cached, or a local path
        local = Path(model_id) / "config.json"
        if local.exists():
            cfg = json.loads(local.read_text())
        else:
            c.log(f"train: could not read the layer count for {model_id} ({exc})")
            return None
    return cfg.get("num_hidden_layers")


def wandb_env(run_name: str, project: str, model_id: str) -> dict:
    """The trainer's own wandb run, named and grouped like the rest of the account.

    mlx-lm exposes no run-name flag and would otherwise name the run after the adapter
    directory, so the name travels in the subprocess environment. The fine-tune and the
    scoring pass share one group, so a round reads as a single experiment with two
    stages rather than two unrelated rows.
    """
    return {"WANDB_NAME": run_name, "WANDB_RUN_GROUP": run_name, "WANDB_JOB_TYPE": "sft",
            "WANDB_PROJECT": project, "WANDB_TAGS": ",".join(["lora", c.model_stem(model_id)]),
            "WANDB_NOTES": "DEBRIS tag schema fine-tune (spec 5.5)"}


def train(iters: int, num_layers: int, model_id: str, batch_size: int,
          run_name: str | None = None) -> Path:
    log_path = c.ROOT / "data" / "train" / "lora_train.log"
    # Checkpoints from a previous, longer run would still be here, and the validation
    # loss in this run's log says nothing about them.
    for stale in ADAPTER.glob("*_adapters.safetensors"):
        stale.unlink()
    (ADAPTER / "adapters_last.safetensors").unlink(missing_ok=True)
    cmd = ["mlx_lm.lora", "--model", model_id, "--train", "--data", str(c.TRAIN),
           "--fine-tune-type", "lora", "--num-layers", str(num_layers),
           "--batch-size", str(batch_size), "--iters", str(iters),
           "--learning-rate", "1e-5", "--adapter-path", str(ADAPTER), "--seed", "42",
           "--steps-per-eval", "100", "--steps-per-report", "20"]
    cfg = c.load_toml("wandb.toml")
    project = cfg.get("project", "debris")
    extra_env = None
    if c.wandb_api_key():
        cmd += lora_report_args(project)
        if run_name:
            extra_env = wandb_env(run_name, project, model_id)
    run(cmd, log_path, extra_env=extra_env)
    return log_path


def parse_training_log(path: Path) -> list[dict]:
    """Loss curve from the mlx-lm log, for the thin wandb wrapper."""
    points = []
    for line in path.read_text().splitlines():
        if m := re.search(r"Iter (\d+): Train loss ([\d.]+), Learning Rate ([\d.e+-]+)", line):
            points.append({"iter": int(m.group(1)), "train_loss": float(m.group(2)),
                           "learning_rate": float(m.group(3))})
        elif m := re.search(r"Iter (\d+): Val loss ([\d.]+)", line):
            points.append({"iter": int(m.group(1)), "val_loss": float(m.group(2))})
    return points


def checkpoint_rank(metrics: dict) -> tuple[int, float]:
    """How good a checkpoint is: floors cleared first, then how close the rest are.

    Capping each ratio at 1 stops a metric that is already comfortably over its floor
    from paying for one that is under it."""
    met = sum(1 for field, floor in FLOOR.items() if metrics.get(field, 0) >= floor)
    ratios = [min(metrics.get(field, 0) / floor, 1.0) for field, floor in FLOOR.items()]
    return met, sum(ratios) / len(ratios)


def select_checkpoint(iters: int, model_id: str, every: int) -> None:
    """Pick the checkpoint that tags the validation split best, and fuse that one.

    mlx-lm leaves `adapters.safetensors` pointing at the last iteration. Validation loss
    looked like the way to choose a better one, and it is not: the checkpoint with the
    lowest loss scored worse on every field, pathways by six points (DECISIONS.md D24).
    Cross-entropy over the JSON is not the same quantity as agreement field by field, so
    the choice is made on the fields themselves, on the validation split, never on the
    test split that the acceptance floor is measured over.
    """
    final = ADAPTER / "adapters.safetensors"
    candidates = [it for it in range(every, iters + 1, every)
                  if (ADAPTER / f"{it:07d}_adapters.safetensors").exists()]
    if iters not in candidates and (ADAPTER / f"{iters:07d}_adapters.safetensors").exists():
        candidates.append(iters)
    if len(candidates) < 2:
        c.log("train: fewer than two checkpoints on disk; fusing the last adapter")
        return

    shutil.copy(final, ADAPTER / "adapters_last.safetensors")
    staged = ADAPTER.parent / "debris_v1_candidate"
    best: tuple[tuple[int, float], int, dict] | None = None
    for it in candidates:
        staged.mkdir(parents=True, exist_ok=True)
        shutil.copy(ADAPTER / "adapter_config.json", staged / "adapter_config.json")
        shutil.copy(ADAPTER / f"{it:07d}_adapters.safetensors", staged / "adapters.safetensors")
        metrics = score(model_id, str(staged), split="valid", label=f"valid_{it}")
        rank = checkpoint_rank(metrics)
        c.log(f"train: checkpoint {it}: {rank[0]}/{len(FLOOR)} floors, score {rank[1]:.4f}, "
              f"relevant {metrics['relevant_f1']}, organs {metrics['organ_systems_f1']}, "
              f"pathways {metrics['pathways_f1']}")
        if best is None or rank > best[0]:
            best = (rank, it, metrics)
    shutil.rmtree(staged, ignore_errors=True)

    rank, it, _ = best
    shutil.copy(ADAPTER / f"{it:07d}_adapters.safetensors", final)
    (c.TRAIN / "checkpoint_choice.json").write_text(json.dumps(
        {"chosen": it, "of": candidates, "rank": {"floors_met": rank[0], "score": rank[1]},
         "split": "valid", "written": c.now()}, indent=1))
    c.log(f"train: fusing checkpoint {it} of {candidates}, chosen on the validation split")


def fuse(model_id: str) -> None:
    """Merge the adapter into the base weights, de-quantised so transformers can load
    them on the Space. Clear the directory first: a shard left over from a previous
    fuse with a different layout would otherwise sit alongside the new ones."""
    if FUSED.exists():
        shutil.rmtree(FUSED)
    run(["mlx_lm.fuse", "--model", model_id, "--adapter-path", str(ADAPTER),
         "--save-path", str(FUSED), "--dequantize"])


def quantise() -> None:
    """The 4-bit copy for Studio-side inference. mlx_lm.convert refuses to write into a
    directory that already exists, so a second run has to clear the previous copy."""
    if Q4.exists():
        shutil.rmtree(Q4)
    run(["mlx_lm.convert", "--hf-path", str(FUSED), "-q", "--mlx-path", str(Q4)])


# ---------------------------------------------------------------------- scoring

def micro_f1(pairs: list[tuple[set, set]]) -> float:
    tp = sum(len(a & b) for a, b in pairs)
    fp = sum(len(b - a) for a, b in pairs)
    fn = sum(len(a - b) for a, b in pairs)
    if tp == 0:
        return 0.0 if (fp or fn) else 1.0
    precision = tp / (tp + fp)
    recall = tp / (tp + fn)
    return 2 * precision * recall / (precision + recall)


def binary_f1(truth: list[bool], pred: list[bool]) -> float:
    tp = sum(1 for t, p in zip(truth, pred) if t and p)
    fp = sum(1 for t, p in zip(truth, pred) if not t and p)
    fn = sum(1 for t, p in zip(truth, pred) if t and not p)
    if tp == 0:
        return 0.0 if (fp or fn) else 1.0
    return 2 * tp / (2 * tp + fp + fn)


def score(model_path: str, adapter_path: str | None = None, split: str = "test",
          label: str = "fused") -> dict:
    """Score a model against the held-out split, field by field (spec 5.5).

    Predictions are written to `data/train/predictions_<label>.jsonl` so a shortfall can
    be read field by field, and one rung of the fallback ladder compared with the next,
    without scoring the split again.
    """
    from pipeline.tag import LocalTagger

    rows = list(c.jsonl_read(c.TRAIN / f"{split}_meta.jsonl"))
    if not rows:
        raise SystemExit(f"no {split}_meta.jsonl: run `pixi run bootstrap split` first")
    tagger = LocalTagger(model_path, adapter_path)

    truth_rel, pred_rel = [], []
    poly, organ, path_pairs, disease = [], [], [], []
    rung_exact = rung_within = valid_json = 0
    model_ok = model_n = 0
    predictions = []
    started = time.monotonic()
    for i, row in enumerate(rows, 1):
        gold = row["tag"]
        raw_text = tagger.generate(schema.user_prompt(row["paper"]), 0.0)
        raw = schema.extract_json(raw_text)
        valid_json += 1 if raw is not None else 0
        pred, _, _ = schema.validate(raw)
        if pred is None:
            pred = {"relevant": False, "polymers": [], "organ_systems": [], "pathways": [],
                    "disease_categories": [], "evidence_rungs": [],
                    "model_type": "not_applicable"}
        predictions.append({"pmid": row["pmid"], "gold": gold, "pred": pred,
                            "parsed": raw is not None})
        truth_rel.append(bool(gold["relevant"]))
        pred_rel.append(bool(pred["relevant"]))
        poly.append((set(gold["polymers"]), set(pred["polymers"])))
        organ.append((set(gold["organ_systems"]), set(pred["organ_systems"])))
        path_pairs.append((set(gold["pathways"]), set(pred["pathways"])))
        disease.append((set(gold["disease_categories"]), set(pred["disease_categories"])))
        gold_rungs, pred_rungs = set(gold["evidence_rungs"]), set(pred["evidence_rungs"])
        rung_exact += 1 if gold_rungs == pred_rungs else 0
        rung_within += 1 if rungs_within_one(gold_rungs, pred_rungs) else 0
        # model_type is only defined where the paper is relevant: on the rest it is
        # not_applicable, which just restates the relevance call that relevant_f1
        # already measures. Scoring it there would pad the accuracy with 46 % of the
        # split at no cost (see DECISIONS.md D22).
        if gold["relevant"]:
            model_n += 1
            model_ok += 1 if gold["model_type"] == pred["model_type"] else 0
        if i % 20 == 0:
            print(f"  scored {i}/{len(rows)}", flush=True)
    n = len(rows)
    c.jsonl_write(c.TRAIN / f"predictions_{label}.jsonl", predictions)
    return {
        "n": n,
        "relevant_f1": round(binary_f1(truth_rel, pred_rel), 4),
        "polymers_f1": round(micro_f1(poly), 4),
        "organ_systems_f1": round(micro_f1(organ), 4),
        "pathways_f1": round(micro_f1(path_pairs), 4),
        "disease_categories_f1": round(micro_f1(disease), 4),
        "rungs_exact": round(rung_exact / n, 4),
        "rungs_within_one": round(rung_within / n, 4),
        "model_type_accuracy": round(model_ok / model_n, 4) if model_n else 1.0,
        "model_type_n": model_n,
        "valid_json": round(valid_json / n, 4),
        "seconds_per_paper": round((time.monotonic() - started) / n, 2),
        "model": model_path + (f"+{adapter_path}" if adapter_path else ""),
    }


def rungs_within_one(gold: set[int], pred: set[int]) -> bool:
    """True when every gold rung has a predicted rung within one, and vice versa."""
    if gold == pred:
        return True
    if not gold or not pred:
        return False
    return (all(any(abs(g - p) <= 1 for p in pred) for g in gold)
            and all(any(abs(g - p) <= 1 for g in gold) for p in pred))


def meets_floor(metrics: dict) -> list[str]:
    return [f"{field} {metrics.get(field, 0):.3f} < {floor}"
            for field, floor in FLOOR.items() if metrics.get(field, 0) < floor]


def write_model_card(metrics: dict, q4_metrics: dict | None, config: dict,
                     wandb_url: str | None) -> None:
    train_n = sum(1 for _ in c.jsonl_read(c.TRAIN / "train.jsonl"))
    valid_n = sum(1 for _ in c.jsonl_read(c.TRAIN / "valid.jsonl"))
    test_n = sum(1 for _ in c.jsonl_read(c.TRAIN / "test.jsonl"))
    shortfall = meets_floor(metrics)
    rows = "\n".join(f"| {k} | {v} | {FLOOR.get(k, '')} |" for k, v in metrics.items())
    q4_rows = ("\n".join(f"| {k} | {v} |" for k, v in q4_metrics.items())
               if q4_metrics else "| not scored | |")
    (c.ROOT / "MODEL_CARD.md").write_text(f"""# DEBRIS tagger debris_v1

A single LoRA fine-tune of `{config['model_id']}` that turns a PubMed title, journal,
MeSH list and abstract into the DEBRIS tag JSON (spec 5.4). It is trained on the task
and the schema, not on facts: the weekly pipeline never retrains it.

## Training

| | |
|---|---|
| Base model | `{config['model_id']}` |
| Method | LoRA, {config['num_layers']} layers, batch size {config['batch_size']}, {config['iters']} iterations, learning rate 1e-5, seed 42 |
| Data | `debris-train:v1` ({train_n} train, {valid_n} valid, {test_n} test), stratified on relevance and model type |
| Vocabulary | `config/vocab.toml` schema version {c.vocab().get('schema_version')} |
| Labels | {config['label_source']} |
| wandb | {wandb_url or 'offline, under `wandb/`'} |
| Fused model | `data/adapters/debris_v1_fused` (de-quantised safetensors, Hugging Face layout) |
| Quantised | `data/adapters/debris_v1_q4` |

## Test-split metrics

| Field | Value | Acceptance floor |
|---|---|---|
{rows}

## Quantised (q4) comparison

| Field | Value |
|---|---|
{q4_rows}

## Acceptance

{"All acceptance floors met." if not shortfall else "Below floor: " + "; ".join(shortfall)}

## Intended use and limits

DEBRIS tags literature, it does not adjudicate science. A tag records what a paper
reports: a polymer detected, an association observed in a cohort, a mechanism shown
in vitro. Nothing in the schema asserts human causation, and the evidence rungs are
deliberately ordered so that a reader can see how far from a human outcome a given
claim sits. Reviews carry no rungs. Papers the tagger is unsure about are routed to
the review queue and shown as "needs review" rather than silently published.

## Known label limits

Some fields carry more label noise than others, and the measurements behind this are in
DECISIONS.md D22 and D25. A reader of the tagged corpus should know which way each field
errs.

**Evidence rung 5 is a lower bound.** Dose-response is recorded only where the article
reports more than one exposure level, or states a dose or concentration dependent effect.
That rule removed 144 of the original 245 rung-5 labels, most of them papers reporting a
size-dependent rather than a dose-dependent effect, and left 82 instances across the
relevant training rows. The tagger's commonest rung error is leaving rung 5 off a paper
that has it, so a paper shown without rung 5 may still have demonstrated a dose response.
The error does not run the other way to any comparable degree.

**`systemic` is a soft organ label.** It carries its own vocabulary in the abstract in
29 % of instances, against 100 % for renal and 98 % for gastrointestinal, so in practice
it is a residual category for multi-organ or unlocalised work rather than a finding. It is
also the organ system the tagger most often fails to predict.

**`cell_line` and `human_in_vitro` overlap.** Gold `cell_line` names an immortalised line
(Caco-2, HepG2, A549 and the like) in 60 % of its papers and gold `human_in_vitro` in
25 %, while only 16 % of `human_in_vitro` papers mention primary or ex vivo material. The
boundary is therefore not a rule the schema states, and most model-type errors sit on it.
Read `model_type` as a broad design class and not as a precise claim about the material.

**Pathways are over-reported rather than under-reported.** Precision is the weaker side:
the tagger volunteers mechanisms that are plausible for the exposure but not measured in
the paper, and a substantial minority of its false-positive `oxidative_stress` calls have
no oxidative vocabulary anywhere in the abstract. `leachate_chemical_toxicity` is weakly
grounded in both directions. Treat a pathway on a single paper as a pointer to the
abstract rather than as a finding, and weigh the pathway hub on counts across many papers.
""")


def main() -> None:
    ap = argparse.ArgumentParser(description="Train the DEBRIS tagger once")
    ap.add_argument("--iters", type=int, default=800)
    ap.add_argument("--num-layers", type=int, default=16)
    ap.add_argument("--batch-size", type=int, default=4)
    ap.add_argument("--model", default=None)
    ap.add_argument("--score-only", action="store_true")
    ap.add_argument("--retrain", action="store_true",
                    help="fine-tune again even if an adapter is already saved")
    ap.add_argument("--skip-q4-score", action="store_true")
    ap.add_argument("--round", type=int, default=0, metavar="NN",
                    help="force the wandb round number instead of reading it from the project")
    ap.add_argument("--select-every", type=int, default=0, metavar="N",
                    help="score every Nth checkpoint on the validation split and fuse "
                         "the best one instead of the last (about 5 min per checkpoint)")
    args = ap.parse_args()

    tuning = c.tuning()
    model_id = args.model or tuning.get("model_id", "Qwen/Qwen2.5-3B-Instruct")
    depth = model_depth(model_id)
    if depth and args.num_layers > depth:
        c.log(f"train: {model_id} has {depth} layers, so adapting all {depth} "
              f"rather than the {args.num_layers} requested")
        args.num_layers = depth
    # The round is read from the wandb project, so it stays right across machines and
    # after a clone, and is fixed once here: the fine-tune and the scoring pass must land
    # in the same round rather than one ticking past the other.
    wandb_cfg = c.load_toml("wandb.toml")
    project = wandb_cfg.get("project", "debris")
    round_number = args.round or c.wandb_round(project, wandb_cfg.get("entity") or None)
    run_name = c.wandb_run_name(project, model_id, round_number)
    c.log(f"train: wandb run {run_name}")
    config = {"model_id": model_id, "iters": args.iters, "num_layers": args.num_layers,
              "batch_size": args.batch_size, "round": round_number, "round_name": run_name,
              "select_every": args.select_every,
              "label_source": "build session (no ANTHROPIC_API_KEY)" if not c.api_key("ANTHROPIC_API_KEY")
              else "claude-sonnet-4-5"}

    log_path = c.TRAIN / "lora_train.log"
    if not args.score_only:
        if (ADAPTER / "adapters.safetensors").exists() and not args.retrain:
            c.log("train: adapter already present, reusing it (--retrain to start over)")
        else:
            started = time.monotonic()
            log_path = train(args.iters, args.num_layers, model_id, args.batch_size,
                             run_name=run_name)
            c.log(f"train: LoRA finished in {(time.monotonic() - started) / 60:.1f} min")
            if args.select_every:
                select_checkpoint(args.iters, model_id, args.select_every)
        if (FUSED / "config.json").exists() and not args.retrain:
            c.log("train: fused model already present, reusing it")
        else:
            fuse(model_id)
            c.log("train: fused")
        if (Q4 / "config.json").exists() and not args.retrain:
            c.log("train: quantised model already present, reusing it")
        else:
            quantise()
            c.log("train: quantised")

    metrics = score(str(FUSED) if FUSED.exists() else model_id,
                    None if FUSED.exists() else str(ADAPTER), label="fused")
    q4_metrics = None
    if Q4.exists() and not args.skip_q4_score:
        q4_metrics = score(str(Q4), label="q4")
        gap = metrics["relevant_f1"] - q4_metrics["relevant_f1"]
        c.log(f"train: q4 vs fused relevant F1 gap {gap:+.3f}")
        marker = c.ROOT / "USE_FUSED"
        if gap > 0.02:
            marker.write_text(
                "q4 lost more than 2 F1 points against the fused model; inference uses "
                "debris_v1_fused.\n")
        elif marker.exists():
            # A previous run's q4 copy scored badly. This one does not, so clear the
            # marker rather than leave inference pointed at the 6 GB fused weights.
            marker.unlink()
            c.log("train: q4 now matches the fused model, cleared USE_FUSED")
    (c.TRAIN / "metrics.json").write_text(json.dumps(
        {"fused": metrics, "q4": q4_metrics, "floor": FLOOR,
         "shortfall": meets_floor(metrics), "curve": parse_training_log(log_path)
         if log_path.exists() else []}, indent=1))

    wandb_url = log_to_wandb(metrics, q4_metrics, config, log_path)
    write_model_card(metrics, q4_metrics, config, wandb_url)
    shortfall = meets_floor(metrics)
    c.log(f"train: metrics {json.dumps(metrics)}")
    c.log("train: acceptance floor met" if not shortfall
          else f"train: BELOW FLOOR: {'; '.join(shortfall)}")


def log_to_wandb(metrics: dict, q4_metrics: dict | None, config: dict,
                 log_path: Path) -> str | None:
    try:
        import wandb
    except ImportError:
        return None
    cfg = c.load_toml("wandb.toml")
    if not c.wandb_api_key():
        os.environ["WANDB_MODE"] = "offline"
    group = config.get("round_name") or "debris"
    run_ = wandb.init(project=cfg.get("project", "debris"), entity=cfg.get("entity") or None,
                      job_type="eval", name=f"{group}-eval", group=group, dir=str(c.ROOT),
                      tags=["lora", c.model_stem(config.get("model_id", "")), "test-split"],
                      notes="Acceptance metrics over the frozen test split (spec 5.5)",
                      config=config)
    # mlx_lm.lora streams its own curve when the version supports it; the log is replayed
    # here as well so this run carries loss against iteration whether it did or not.
    for point in parse_training_log(log_path) if log_path.exists() else []:
        run_.log(point, step=point["iter"])
    # Every acceptance metric as a scalar in the run summary, not only inside the table
    # below: a table cannot be sorted or charted across runs, and comparing one ladder
    # rung with the next is the whole reason for tracking them (D28).
    for field, value in metrics.items():
        if isinstance(value, (int, float)):
            run_.summary[f"test/{field}"] = value
            floor = FLOOR.get(field)
            if floor is not None:
                run_.summary[f"floor_gap/{field}"] = round(value - floor, 4)
    run_.summary["floors_met"] = sum(1 for f, fl in FLOOR.items() if metrics.get(f, 0) >= fl)
    run_.summary["floors_total"] = len(FLOOR)
    if q4_metrics:
        for field, value in q4_metrics.items():
            if isinstance(value, (int, float)):
                run_.summary[f"q4/{field}"] = value
    # wandb fixes a Table column's type from the first row, and these rows mix numbers
    # with the model path, so every cell goes in as text.
    table = wandb.Table(columns=["field", "value", "floor", "meets"])
    for field, value in metrics.items():
        floor = FLOOR.get(field)
        table.add_data(field, str(value), "" if floor is None else str(floor),
                       "" if floor is None else ("yes" if value >= floor else "no"))
    run_.log({"test_metrics": table})
    if q4_metrics:
        comparison = wandb.Table(columns=["field", "fused", "q4"])
        for field in metrics:
            if field in q4_metrics:
                comparison.add_data(field, str(metrics[field]), str(q4_metrics[field]))
        run_.log({"fused_vs_q4": comparison})
    if (c.ROOT / "MODEL_CARD.md").exists():
        artifact = wandb.Artifact("debris-tagger-card", type="model-card")
        artifact.add_file(str(c.ROOT / "MODEL_CARD.md"))
        run_.log_artifact(artifact)
    url = getattr(run_, "url", None) or "offline"
    run_.finish()
    return url


if __name__ == "__main__":
    main()
