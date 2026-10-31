"""The lab: test training ideas on a small model with cross-validation (LAB_PLAN.md).

An experiment is a TOML file under config/lab/: the model, how long to train, which folds
and seeds, which checkpoints to score, and the switches that make one data variant
different from another. Every variant is rebuilt from the canonical labelled records
(data/train/{train,valid}_meta.jsonl) by a deterministic transform, so no label is ever
edited in place and any round can be rebuilt exactly. The test split is never touched.

  pixi run lab folds                  # assign the three folds, once
  pixi run lab run phase0-baseline    # train and score one experiment; resumable
  pixi run lab phase1 --iters 400     # write the eight Phase 1 factorial configs
  pixi run lab report                 # rebuild LAB_REPORT.md
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import random
import shutil
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import common as c
from pipeline import lab_v2
from pipeline import schema
from pipeline import train as production

LAB = c.DATA / "lab"
FOLDS = LAB / "folds.json"
CONFIGS = c.ROOT / "config" / "lab"
REPORT = c.ROOT / "LAB_REPORT.md"
FOLD_SEED = 20261029
N_FOLDS = 3
VALID_ROWS = 64          # held-out rows mlx-lm reports validation loss on; never decides
SCORE_BATCH = 16
MAX_TOKENS = 400
BOOTSTRAP = 2000

# The answer order switch C puts the decisive fields first, because the model writes left
# to right and the evidence rungs depend on the study design.
ANSWER_ORDER = ("relevant", "model_type", "evidence_rungs", "polymers", "size_class",
                "organ_systems", "disease_categories", "disease_terms", "pathways",
                "pet_specific", "confidence", "summary")

FLOOR = production.FLOOR
# The Phase 1 target for switch A, which is expected to move every field: the plain mean
# of the eight floor metrics, so no single field can carry it.
COMPOSITE = "floor_mean"


# ---------------------------------------------------------------------------- records

def canonical_records() -> list[dict]:
    """The 1,438 train and validation papers, each with its paper and its v1 tag."""
    rows = []
    for split in ("train", "valid"):
        rows += list(c.jsonl_read(c.TRAIN / f"{split}_meta.jsonl"))
    if not rows:
        raise SystemExit("no canonical records: run `pixi run bootstrap split` first")
    return rows


def test_pmids() -> set[str]:
    return {r["pmid"] for r in c.jsonl_read(c.TRAIN / "test_meta.jsonl")}


def assign_folds(records: list[dict], force: bool = False) -> dict[str, int]:
    """Three folds, stratified on relevance and study design as the original split was.

    Written once and never redrawn unless forced, because a fold that moved between two
    experiments would make them incomparable."""
    if FOLDS.exists() and not force:
        return {k: int(v) for k, v in json.loads(FOLDS.read_text())["assignment"].items()}
    rng = random.Random(FOLD_SEED)
    strata: dict[tuple, list[str]] = collections.defaultdict(list)
    for r in sorted(records, key=lambda r: r["pmid"]):
        strata[(bool(r["tag"]["relevant"]), r["tag"]["model_type"])].append(r["pmid"])
    assignment: dict[str, int] = {}
    offset = 0
    for key in sorted(strata, key=str):
        pmids = strata[key]
        rng.shuffle(pmids)
        # Each stratum starts dealing where the last one stopped, so small strata do not
        # all pile their odd paper into fold 0.
        for i, pmid in enumerate(pmids):
            assignment[pmid] = (offset + i) % N_FOLDS
        offset = (offset + len(pmids)) % N_FOLDS
    leaked = set(assignment) & test_pmids()
    if leaked:
        raise SystemExit(f"{len(leaked)} test-split papers reached the folds; refusing")
    LAB.mkdir(parents=True, exist_ok=True)
    FOLDS.write_text(json.dumps({"seed": FOLD_SEED, "written": c.now(),
                                 "assignment": assignment}, indent=1))
    c.log(f"lab folds: {collections.Counter(assignment.values())}")
    return assignment


# --------------------------------------------------------------------------- variants

def user_prompt(paper: dict, switches: dict) -> str:
    """The paper as the tagger sees it. Switch B adds the PubMed publication types, which
    the labeller saw and the tagger never has, and stops cutting MeSH at 600 characters."""
    if not switches.get("types"):
        return schema.user_prompt(paper)
    mesh = paper.get("mesh") or ""
    if isinstance(mesh, list):
        mesh = "; ".join(mesh)
    abstract = (paper.get("abstract") or "").strip()
    if len(abstract) > 6000:
        abstract = abstract[:6000] + " [truncated]"
    return (f"TITLE: {paper.get('title','')}\n"
            f"JOURNAL: {paper.get('journal','')} ({paper.get('year') or ''})\n"
            f"TYPES: {paper.get('pub_types') or ''}\n"
            f"MESH: {mesh}\n"
            f"ABSTRACT: {abstract}")


def target(tag: dict, switches: dict) -> str:
    """The answer the model is trained to write."""
    out = dict(tag)
    if switches.get("drop_confidence"):
        out.pop("confidence", None)
    if switches.get("order"):
        out = ({k: out[k] for k in ANSWER_ORDER if k in out}
               | {k: v for k, v in out.items() if k not in ANSWER_ORDER})
    return json.dumps(out, separators=(",", ":"), ensure_ascii=False)


_V2_LABELS: dict | None = None


def v2_label(pmid: str) -> dict | None:
    global _V2_LABELS
    if _V2_LABELS is None:
        _V2_LABELS = lab_v2.labels()
        # Phase 3a papers carry their own v2 labels; they never collide with the lab's.
        enrich = c.DATA / "lab" / "enrich" / "labels_v2.jsonl"
        if enrich.exists():
            _V2_LABELS = {**{r["pmid"]: r for r in c.jsonl_read(enrich)}, **_V2_LABELS}
    return _V2_LABELS.get(pmid)


def enrich_records() -> list[dict]:
    """Phase 3a: the extra labelled papers, which only ever train (pipeline/enrich.py)."""
    path = c.DATA / "lab" / "enrich" / "records.jsonl"
    if not path.exists():
        raise SystemExit("no enrichment labels: run `pixi run python pipeline/enrich.py merge`")
    return list(c.jsonl_read(path))


def gold_for(record: dict, cfg: dict) -> dict:
    """The yardstick: v1 gold, or with `gold = "v2"` (every Phase 2 arm) the v2 gold."""
    if cfg.get("gold") == "v2":
        return lab_v2.gold(record["tag"], v2_label(record["pmid"]))
    return record["tag"]


def chat_row(record: dict, switches: dict) -> dict:
    tag = record["tag"]
    if lab_v2.any_on(switches):
        tag = lab_v2.apply(tag, v2_label(record["pmid"]), switches)
    return {"messages": [
        {"role": "system", "content": lab_v2.system_prompt(switches)},
        {"role": "user", "content": user_prompt(record["paper"], switches)},
        {"role": "assistant", "content": target(tag, switches)}]}


# ------------------------------------------------------------------------ experiments

def load_config(name: str) -> dict:
    path = CONFIGS / f"{name}.toml"
    if not path.exists():
        raise SystemExit(f"no experiment {name}: {path} does not exist")
    cfg = c.load_toml(str(path.relative_to(c.ROOT / "config")))
    cfg.setdefault("model", "Qwen/Qwen2.5-1.5B-Instruct")
    cfg.setdefault("num_layers", 16)
    cfg.setdefault("iters", 400)
    cfg.setdefault("save_every", 100)
    cfg.setdefault("learning_rate", 1e-5)
    cfg.setdefault("batch_size", 4)
    cfg.setdefault("folds", list(range(N_FOLDS)))
    cfg.setdefault("seeds", [42])
    cfg.setdefault("score_iters", [cfg["iters"]])
    cfg.setdefault("curve_iters", [])          # scored on fold 0 only, for the curve
    cfg.setdefault("switches", {})
    cfg["name"] = name
    return cfg


def unit_dir(name: str, fold: int, seed: int) -> Path:
    return LAB / name / f"f{fold}-s{seed}"


def experiment_round(cfg: dict) -> str:
    """The wandb round name, fixed the first time an experiment runs so a rerun keeps it."""
    marker = LAB / cfg["name"] / "round.json"
    if marker.exists():
        return json.loads(marker.read_text())["round_name"]
    project = c.load_toml("wandb.toml").get("project", "debris")
    local = [json.loads(p.read_text())["round"] for p in LAB.glob("*/round.json")]
    number = max([c.wandb_round(project)] + [n + 1 for n in local])
    name = c.wandb_run_name(project, cfg["model"], number)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"round": number, "round_name": name}))
    return name


def build_data(cfg: dict, fold: int, records: list[dict], folds: dict[str, int],
               out: Path) -> None:
    switches = cfg["switches"]
    train_rows = [r for r in records if folds[r["pmid"]] != fold]
    if switches.get("enrich"):
        # enrich = "relevant" adds only the on-topic papers: the 111 negatives in the set
        # pushed relevant papers to not relevant (D59).
        extra = enrich_records()
        if switches["enrich"] == "relevant":
            extra = [r for r in extra if r["tag"]["relevant"]]
        train_rows += extra
    held_out = sorted((r for r in records if folds[r["pmid"]] == fold), key=lambda r: r["pmid"])
    random.Random(FOLD_SEED + fold).shuffle(train_rows)
    out.mkdir(parents=True, exist_ok=True)
    c.jsonl_write(out / "train.jsonl", [chat_row(r, switches) for r in train_rows])
    # The final arm's held-out fold is the test split, which must not even be looked at
    # during training, so its validation-loss rows come from the training papers.
    valid = train_rows[:VALID_ROWS] if cfg.get("final") else held_out[:VALID_ROWS]
    c.jsonl_write(out / "valid.jsonl", [chat_row(r, switches) for r in valid])


def train_unit(cfg: dict, fold: int, seed: int, records: list[dict],
               folds: dict[str, int]) -> Path:
    home = unit_dir(cfg["name"], fold, seed)
    adapters = home / "adapters"
    final = adapters / f"{cfg['iters']:07d}_adapters.safetensors"
    if final.exists():
        return adapters
    build_data(cfg, fold, records, folds, home / "data")
    for stale in adapters.glob("*_adapters.safetensors"):
        stale.unlink()
    # Through the capped launcher, so a cap the queue set reaches the training too (D36);
    # with no cap set it is plain mlx_lm.lora.
    cmd = [sys.executable, str(c.ROOT / "pipeline" / "mlx_capped.py"), "mlx_lm.lora",
           "--model", cfg["model"], "--train", "--data", str(home / "data"),
           "--fine-tune-type", "lora", "--num-layers", str(cfg["num_layers"]),
           "--batch-size", str(cfg["batch_size"]), "--iters", str(cfg["iters"]),
           "--learning-rate", str(cfg["learning_rate"]), "--adapter-path", str(adapters),
           "--seed", str(seed), "--save-every", str(cfg["save_every"]),
           "--steps-per-eval", "100", "--steps-per-report", "20", "--val-batches", "16"]
    if cfg["switches"].get("mask_prompt"):
        cmd.append("--mask-prompt")
    # Recomputes activations in the backward pass: same gradients, a fraction of the
    # memory. The 7B peaks at 116 GB of 128 without it and dies on any other load (D62).
    if cfg.get("grad_checkpoint"):
        cmd.append("--grad-checkpoint")
    c.log(f"lab {cfg['name']} f{fold} s{seed}: training {cfg['iters']} iterations")
    started = time.monotonic()
    production.run(cmd, home / "train.log")
    minutes = (time.monotonic() - started) / 60
    c.manifest_write("lab", {"experiment": cfg["name"], "fold": fold, "seed": seed,
                             "stage": "trained", "minutes": round(minutes, 1), "at": c.now()})
    c.log(f"lab {cfg['name']} f{fold} s{seed}: trained in {minutes:.1f} min")
    return adapters


def checkpoint(adapters: Path, iteration: int) -> Path:
    """A directory mlx-lm can load holding just one checkpoint's weights."""
    source = adapters / f"{iteration:07d}_adapters.safetensors"
    if not source.exists():
        raise SystemExit(f"no checkpoint at iteration {iteration} in {adapters}")
    home = adapters.parent / f"ckpt-{iteration}"
    home.mkdir(exist_ok=True)
    shutil.copy(adapters / "adapter_config.json", home / "adapter_config.json")
    shutil.copy(source, home / "adapters.safetensors")
    return home


def generate_batch(model, tokenizer, prompts: list[str], system: str | None = None) -> list[str]:
    """Greedy answers for a batch of papers, in the order given."""
    from mlx_lm import batch_generate

    tokens = [tokenizer.apply_chat_template(
        [{"role": "system", "content": system or schema.SYSTEM_PROMPT},
         {"role": "user", "content": p}], add_generation_prompt=True) for p in prompts]
    # Similar lengths batch together with less padding; the answers are put back in order.
    order = sorted(range(len(tokens)), key=lambda i: len(tokens[i]))
    answers: list[str] = [""] * len(tokens)
    for start in range(0, len(order), SCORE_BATCH):
        chunk = order[start:start + SCORE_BATCH]
        result = batch_generate(model, tokenizer, [tokens[i] for i in chunk],
                                max_tokens=MAX_TOKENS)
        for i, text in zip(chunk, result.texts):
            answers[i] = text
    return answers


def score_unit(cfg: dict, fold: int, seed: int, iteration: int, records: list[dict],
               folds: dict[str, int]) -> dict:
    home = unit_dir(cfg["name"], fold, seed)
    out = home / f"pred-{iteration}.jsonl"
    if out.exists():
        rows = list(c.jsonl_read(out))
        return production.field_metrics([(r["gold"], r["pred"]) for r in rows])
    from mlx_lm import load

    held_out = sorted((r for r in records if folds[r["pmid"]] == fold), key=lambda r: r["pmid"])
    # Only the smoke test sets this: a partial fold is never a lab result.
    held_out = held_out[:cfg["score_limit"]] if cfg.get("score_limit") else held_out
    model, tokenizer = load(cfg["model"], adapter_path=str(checkpoint(home / "adapters", iteration)))
    started = time.monotonic()
    texts = generate_batch(model, tokenizer,
                           [user_prompt(r["paper"], cfg["switches"]) for r in held_out],
                           system=lab_v2.system_prompt(cfg["switches"]))
    rows = []
    for record, text in zip(held_out, texts):
        raw = schema.extract_json(text)
        pred, problems = lab_v2.validate(raw, cfg["switches"])
        rows.append({"pmid": record["pmid"], "gold": gold_for(record, cfg),
                     "pred": pred if pred is not None else dict(production.UNPARSED),
                     "parsed": raw is not None, "problems": problems})
    seconds = (time.monotonic() - started) / max(1, len(rows))
    c.jsonl_write(out, rows)
    metrics = production.field_metrics([(r["gold"], r["pred"]) for r in rows])
    if cfg.get("gold") == "v2":
        metrics.update(lab_v2.metrics([(r["gold"], r["pred"]) for r in rows]))
    metrics["valid_json"] = round(sum(r["parsed"] for r in rows) / max(1, len(rows)), 4)
    metrics["seconds_per_paper"] = round(seconds, 3)
    c.manifest_write("lab", {"experiment": cfg["name"], "fold": fold, "seed": seed,
                             "stage": "scored", "iter": iteration, "n": len(rows),
                             "metrics": metrics, "at": c.now()})
    c.log(f"lab {cfg['name']} f{fold} s{seed} @ {iteration}: "
          + ", ".join(f"{k} {metrics[k]}" for k in FLOOR if k in metrics)
          + f", {seconds:.2f} s/paper")
    del model
    return metrics


def log_unit(cfg: dict, fold: int, seed: int, scored: dict[int, dict]) -> None:
    """One wandb run per fold and seed: the loss curve, and every scored checkpoint.
    A failure here is logged and never fails the round."""
    import os

    try:
        import wandb
    except ImportError:
        return
    import secrets

    home = unit_dir(cfg["name"], fold, seed)
    try:
        round_name = experiment_round(cfg)
        run_name = f"{round_name}-f{fold}" + (f"-s{seed}" if seed != 42 else "")
        project = c.load_toml("wandb.toml")
        # A stored id, so scoring more checkpoints later adds to the same run rather than
        # starting a second one for the same fold and seed.
        id_file = home / "wandb_id"
        run_id = id_file.read_text().strip() if id_file.exists() else secrets.token_hex(4)
        id_file.write_text(run_id)
        if not c.wandb_api_key():
            os.environ["WANDB_MODE"] = "offline"
        run = wandb.init(project=project.get("project", "debris"),
                         entity=project.get("entity") or None, id=run_id, resume="allow",
                         name=run_name, group=round_name, job_type="lab",
                         dir=str(c.ROOT), reinit=True,
                         config={**{k: v for k, v in cfg.items() if k != "switches"},
                                 **{f"switch/{k}": v for k, v in cfg["switches"].items()},
                                 "fold": fold, "seed": seed, "round_name": round_name})
        if not run.summary.get("curve_logged"):
            for point in production.parse_training_log(home / "train.log"):
                step = point.pop("iter")
                run.log({f"train/{k}": v for k, v in point.items()}, step=step)
            run.summary["curve_logged"] = True
        for iteration, metrics in sorted(scored.items()):
            for k, v in metrics.items():
                if isinstance(v, (int, float)):
                    run.summary[f"eval_{iteration}/{k}"] = v
        final = scored.get(max(scored)) if scored else {}
        for k, v in final.items():
            if isinstance(v, (int, float)):
                run.summary[f"lab/{k}"] = v
        run.finish()
    except Exception as exc:  # noqa: BLE001 - wandb never stops the lab
        c.log(f"lab wandb: {type(exc).__name__}: {exc}")


def final_split() -> tuple[list[dict], dict[str, int]]:
    """Phase 5: every cross-validation paper trains, and the frozen test split is the one
    held-out fold (fold 0). Scored once, at one checkpoint fixed before the run."""
    records = canonical_records()
    test = list(c.jsonl_read(c.TRAIN / "test_meta.jsonl"))
    return records + test, {**{r["pmid"]: 1 for r in records}, **{r["pmid"]: 0 for r in test}}


def import_predictions(cfg: dict) -> None:
    """A production round's saved test predictions as a lab unit, scored against the same
    gold as the lab's final arm, so the two pair paper by paper without retraining it."""
    out = unit_dir(cfg["name"], 0, 42) / f"pred-{cfg['iters']}.jsonl"
    if out.exists():
        return
    test = {r["pmid"]: r for r in c.jsonl_read(c.TRAIN / "test_meta.jsonl")}
    rows = [{"pmid": r["pmid"], "gold": gold_for(test[r["pmid"]], cfg), "pred": r["pred"],
             "parsed": r.get("parsed", True), "problems": r.get("problems", [])}
            for r in c.jsonl_read(c.ROOT / cfg["predictions"])]
    out.parent.mkdir(parents=True, exist_ok=True)
    c.jsonl_write(out, rows)
    metrics = production.field_metrics([(r["gold"], r["pred"]) for r in rows])
    if cfg.get("gold") == "v2":
        metrics.update(lab_v2.metrics([(r["gold"], r["pred"]) for r in rows]))
    c.manifest_write("lab", {"experiment": cfg["name"], "fold": 0, "seed": 42, "stage": "scored",
                             "iter": cfg["iters"], "n": len(rows), "metrics": metrics, "at": c.now()})
    c.log(f"lab {cfg['name']}: imported {len(rows)} predictions from {cfg['predictions']}")


def run_experiment(name: str) -> None:
    cfg = load_config(name)
    if cfg.get("reuse"):
        c.log(f"lab {name}: reuses {cfg['reuse']}, nothing to train")
        return
    if cfg.get("predictions"):
        import_predictions(cfg)
        return
    if cfg.get("final"):
        records, folds = final_split()
    else:
        records = canonical_records()
        folds = assign_folds(records)
    experiment_round(cfg)
    for fold in cfg["folds"]:
        for seed in cfg["seeds"]:
            adapters = train_unit(cfg, fold, seed, records, folds)
            wanted = list(cfg["score_iters"]) + (list(cfg["curve_iters"]) if fold == 0 else [])
            scored = {}
            for iteration in sorted(set(wanted)):
                if not (adapters / f"{iteration:07d}_adapters.safetensors").exists():
                    c.log(f"lab {name}: no checkpoint {iteration} for f{fold} s{seed}; skipped")
                    continue
                scored[iteration] = score_unit(cfg, fold, seed, iteration, records, folds)
            log_unit(cfg, fold, seed, scored)
    c.log(f"lab {name}: done")


# ---------------------------------------------------------------------- Phase 1 design

PHASE1 = {  # A mask the prompt, B publication types and full MeSH, C answer order,
    # D drop confidence. D = A x B x C: a half fraction of resolution IV.
    1: (0, 0, 0, 0), 2: (1, 0, 0, 1), 3: (0, 1, 0, 1), 4: (1, 1, 0, 0),
    5: (0, 0, 1, 1), 6: (1, 0, 1, 0), 7: (0, 1, 1, 0), 8: (1, 1, 1, 1),
}
FACTORS = {"A": ("mask_prompt", COMPOSITE), "B": ("types", "model_type_accuracy"),
           "C": ("order", "rungs_within_one"), "D": ("drop_confidence", None)}


def write_phase1(iters: int) -> None:
    CONFIGS.mkdir(parents=True, exist_ok=True)
    for number, levels in PHASE1.items():
        switches = {FACTORS[f][0]: bool(level) for f, level in zip("ABCD", levels)}
        lines = [f'description = "Phase 1 configuration {number}: '
                 + ", ".join(f"{f} {'on' if l else 'off'}" for f, l in zip("ABCD", levels)) + '"',
                 f"iters = {iters}", "folds = [0, 1, 2]", "seeds = [42]",
                 'compare_to = "phase1-c1"', ""]
        if number == 1:
            # Configuration 1 is the current recipe, which is exactly the Phase 0 baseline
            # at the same iteration count: reuse its three trainings rather than repeat them.
            lines.insert(1, 'reuse = "phase0-baseline"')
        lines.append("[switches]")
        lines += [f"{k} = {str(v).lower()}" for k, v in switches.items()]
        (CONFIGS / f"phase1-c{number}.toml").write_text("\n".join(lines) + "\n")
    c.log(f"lab: wrote eight Phase 1 configurations at {iters} iterations")


# ----------------------------------------------------------------------------- report

def pooled(name: str, iteration: int | None = None, seed: int = 42,
           folds: list[int] | None = None) -> dict[str, dict] | None:
    """An experiment's predictions at one checkpoint, all folds together, by pmid."""
    cfg = load_config(name)
    if cfg.get("reuse"):
        return pooled(cfg["reuse"], iteration or cfg["iters"], seed, folds)
    iteration = iteration or cfg.get("report_iter") or max(cfg["score_iters"])
    out: dict[str, dict] = {}
    for fold in folds if folds is not None else cfg["folds"]:
        path = unit_dir(name, fold, seed) / f"pred-{iteration}.jsonl"
        if not path.exists():
            return None
        for row in c.jsonl_read(path):
            out[row["pmid"]] = row
    return out


def paper_stats(rows: list[dict]):
    """Per-paper counts from which every field metric is a sum, so a bootstrap resample is
    an index rather than a rescoring. Checked against field_metrics on load."""
    import numpy as np

    def counts(field):
        tp = [len(set(r["gold"][field]) & set(r["pred"][field])) for r in rows]
        fp = [len(set(r["pred"][field]) - set(r["gold"][field])) for r in rows]
        fn = [len(set(r["gold"][field]) - set(r["pred"][field])) for r in rows]
        return np.array(tp), np.array(fp), np.array(fn)

    stats = {"rel": (np.array([bool(r["gold"]["relevant"]) for r in rows]),
                     np.array([bool(r["pred"]["relevant"]) for r in rows]))}
    for field in ("polymers", "organ_systems", "pathways", "disease_categories"):
        stats[field] = counts(field)
    stats["rung_exact"] = np.array([set(r["gold"]["evidence_rungs"]) == set(r["pred"]["evidence_rungs"])
                                    for r in rows])
    stats["rung_within"] = np.array([production.rungs_within_one(
        set(r["gold"]["evidence_rungs"]), set(r["pred"]["evidence_rungs"])) for r in rows])
    stats["model_n"] = np.array([bool(r["gold"]["relevant"]) for r in rows])
    stats["model_ok"] = np.array([bool(r["gold"]["relevant"]) and r["gold"]["model_type"] == r["pred"]["model_type"]
                                  for r in rows])
    stats["parsed"] = np.array([bool(r.get("parsed", True)) for r in rows])
    return stats


def stats_metrics(s, idx) -> dict:
    def f1(tp, fp, fn):
        if tp == 0:
            return 0.0 if (fp or fn) else 1.0
        return 2 * tp / (2 * tp + fp + fn)

    truth, pred = s["rel"][0][idx], s["rel"][1][idx]
    out = {"relevant_f1": f1(int((truth & pred).sum()), int((~truth & pred).sum()),
                             int((truth & ~pred).sum()))}
    for field, key in (("polymers", "polymers_f1"), ("organ_systems", "organ_systems_f1"),
                       ("pathways", "pathways_f1"), ("disease_categories", "disease_categories_f1")):
        tp, fp, fn = (a[idx].sum() for a in s[field])
        out[key] = f1(int(tp), int(fp), int(fn))
    n = len(idx)
    out["rungs_exact"] = float(s["rung_exact"][idx].sum() / n)
    out["rungs_within_one"] = float(s["rung_within"][idx].sum() / n)
    model_n = int(s["model_n"][idx].sum())
    out["model_type_accuracy"] = float(s["model_ok"][idx].sum() / model_n) if model_n else 1.0
    out["valid_json"] = float(s["parsed"][idx].sum() / n)
    out[COMPOSITE] = sum(out[k] for k in FLOOR) / len(FLOOR)
    return out


def checked_stats(rows: list[dict]):
    import numpy as np

    s = paper_stats(rows)
    fast = stats_metrics(s, np.arange(len(rows)))
    slow = production.field_metrics([(r["gold"], r["pred"]) for r in rows])
    for k, v in slow.items():
        if k in fast and abs(fast[k] - v) > 6e-5:
            raise SystemExit(f"lab bootstrap disagrees with field_metrics on {k}: {fast[k]} vs {v}")
    return s


def bootstrap(aligned: list[list[dict]], contrast) -> dict[str, tuple[float, float, float]]:
    """Point estimate and 95 % interval of contrast(metrics per experiment), resampling the
    same papers for every experiment."""
    import numpy as np

    stats = [checked_stats(rows) for rows in aligned]
    n = len(aligned[0])
    full = np.arange(n)
    point = contrast([stats_metrics(s, full) for s in stats])
    rng = np.random.default_rng(7)
    draws = collections.defaultdict(list)
    for _ in range(BOOTSTRAP):
        idx = rng.integers(0, n, n)
        for k, v in contrast([stats_metrics(s, idx) for s in stats]).items():
            draws[k].append(v)
    return {k: (point[k], float(np.quantile(draws[k], 0.025)), float(np.quantile(draws[k], 0.975)))
            for k in point}


def aligned_rows(experiments: list[dict[str, dict]]) -> list[list[dict]]:
    shared = sorted(set.intersection(*(set(e) for e in experiments)))
    return [[e[p] for p in shared] for e in experiments]


METRICS = list(FLOOR) + [COMPOSITE]


def fmt_ci(point: float, lo: float, hi: float, signed: bool = False) -> str:
    sign = "+" if signed else ""
    return f"{point:{sign}.3f} [{lo:{sign}.3f}, {hi:{sign}.3f}]"


def report() -> None:
    # `report = false` keeps a run like the smoke test, which scores a partial fold, out.
    names = sorted(p.stem for p in CONFIGS.glob("*.toml")
                   if load_config(p.stem).get("report", True))
    lines = ["# DEBRIS lab report", "",
             f"Generated {c.now()} by `pixi run lab report` from the predictions under "
             "`data/lab/`. The plan and the rules for adopting an idea are in LAB_PLAN.md. "
             "Every interval is a 95 % paired bootstrap over papers "
             f"({BOOTSTRAP} resamples); `{COMPOSITE}` is the plain mean of the eight floor "
             "metrics.", ""]

    # Each experiment on its own
    lines += ["## Experiments", "",
              "| experiment | round | papers | " + " | ".join(METRICS) + " |",
              "|---" * (len(METRICS) + 3) + "|"]
    results = {}
    for name in names:
        rows = pooled(name)
        if not rows:
            continue
        results[name] = rows
        aligned = aligned_rows([rows])
        est = bootstrap(aligned, lambda m: m[0])
        marker = LAB / (load_config(name).get("reuse") or name) / "round.json"
        round_name = json.loads(marker.read_text())["round_name"] if marker.exists() else ""
        lines.append(f"| {name} | {round_name.rsplit('-', 1)[-1]} | {len(rows)} | "
                     + " | ".join(f"{est[k][0]:.3f} ±{(est[k][2] - est[k][1]) / 2:.3f}"
                                  for k in METRICS) + " |")
    lines.append("")

    # Phase 0: the learning curve on fold 0 and the seed spread
    if (CONFIGS / "phase0-baseline.toml").exists():
        cfg = load_config("phase0-baseline")
        curve = []
        for iteration in sorted(set(cfg["curve_iters"]) | set(cfg["score_iters"])):
            rows = pooled("phase0-baseline", iteration, folds=[0])
            if rows:
                m = stats_metrics(checked_stats(list(rows.values())),
                                  __import__("numpy").arange(len(rows)))
                curve.append(f"| {iteration} | " + " | ".join(f"{m[k]:.3f}" for k in METRICS) + " |")
        if curve:
            lines += ["## Phase 0: learning curve, fold 0", "",
                      "| iteration | " + " | ".join(METRICS) + " |",
                      "|---" * (len(METRICS) + 1) + "|"] + curve + [""]
    if (CONFIGS / "phase0-seeds.toml").exists():
        cfg = load_config("phase0-seeds")
        runs = {42: pooled("phase0-baseline", cfg["score_iters"][0], folds=[0])}
        for seed in cfg["seeds"]:
            runs[seed] = pooled("phase0-seeds", cfg["score_iters"][0], seed=seed, folds=[0])
        if all(runs.values()):
            import numpy as np
            per_seed = {s: stats_metrics(checked_stats(list(r.values())), np.arange(len(r)))
                        for s, r in runs.items()}
            lines += ["## Phase 0: seed spread, fold 0", "",
                      "Training noise alone: the same data and fold, different seeds.", "",
                      "| metric | " + " | ".join(f"seed {s}" for s in per_seed) + " | range |",
                      "|---" * (len(per_seed) + 2) + "|"]
            for k in METRICS:
                vals = [per_seed[s][k] for s in per_seed]
                lines.append(f"| {k} | " + " | ".join(f"{v:.3f}" for v in vals)
                             + f" | {max(vals) - min(vals):.3f} |")
            lines.append("")

    # Comparisons against a declared reference
    comparisons = []
    for name in names:
        cfg = load_config(name)
        ref = cfg.get("compare_to")
        if not ref or ref == name or name not in results or ref not in results:
            continue
        aligned = aligned_rows([results[ref], results[name]])
        eff = bootstrap(aligned, lambda m: {k: m[1][k] - m[0][k] for k in METRICS})
        comparisons.append(f"| {name} vs {ref} | " + " | ".join(
            fmt_ci(*eff[k], signed=True) + (" **real**" if eff[k][1] > 0 or eff[k][2] < 0 else "")
            for k in METRICS) + " |")
    if comparisons:
        lines += ["## Comparisons", "",
                  "Effect of each experiment over its reference. **real** marks an interval "
                  "that excludes zero.", "",
                  "| comparison | " + " | ".join(METRICS) + " |",
                  "|---" * (len(METRICS) + 1) + "|"] + comparisons + [""]

    # Phase 1: main effects of the factorial
    have_phase1 = all((CONFIGS / f"phase1-c{n}.toml").exists() for n in PHASE1)
    phase1 = {n: pooled(f"phase1-c{n}") for n in PHASE1} if have_phase1 else {}
    if phase1 and all(phase1.values()):
        aligned = aligned_rows([phase1[n] for n in PHASE1])
        lines += ["## Phase 1: main effects", "",
                  "Each effect is the mean of the four configurations with the switch on "
                  "minus the four with it off, every paper scored by all eight.", "",
                  "| factor | switch | target | " + " | ".join(METRICS) + " | call |",
                  "|---" * (len(METRICS) + 4) + "|"]
        for f, (switch, goal) in FACTORS.items():
            col = "ABCD".index(f)
            on = [i for i, n in enumerate(PHASE1) if PHASE1[n][col]]
            off = [i for i, n in enumerate(PHASE1) if not PHASE1[n][col]]
            eff = bootstrap(aligned, lambda m, on=on, off=off: {
                k: sum(m[i][k] for i in on) / 4 - sum(m[i][k] for i in off) / 4 for k in METRICS})
            harmed = [k for k in FLOOR if eff[k][2] < 0]
            if goal:
                call = ("adopt" if eff[goal][1] > 0 and not harmed
                        else "reject: harms " + ", ".join(harmed) if harmed else "no effect")
            else:
                call = "adopt (no harm)" if not harmed else "reject: harms " + ", ".join(harmed)
            lines.append(f"| {f} | {switch} | {goal or 'guardrails'} | " + " | ".join(
                fmt_ci(*eff[k], signed=True) for k in METRICS) + f" | {call} |")
        lines.append("")

    lines += lab_v2.report_section(results, {n: load_config(n) for n in results})
    REPORT.write_text("\n".join(lines) + "\n")
    c.log(f"lab report: {len(results)} experiments written to LAB_REPORT.md")


# ------------------------------------------------------------------------------- main

def main() -> int:
    if os.environ.get("DEBRIS_MLX_MEMORY_GB"):
        from pipeline.mlx_capped import apply_caps
        apply_caps()          # this process scores in process: cap it as well
    ap = argparse.ArgumentParser(description="The DEBRIS lab (LAB_PLAN.md)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("folds")
    f.add_argument("--force", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("experiments", nargs="+")
    p = sub.add_parser("phase1")
    p.add_argument("--iters", type=int, required=True)
    sub.add_parser("report")
    args = ap.parse_args()
    if args.cmd == "folds":
        assign_folds(canonical_records(), force=args.force)
    elif args.cmd == "run":
        for name in args.experiments:
            run_experiment(name)
    elif args.cmd == "phase1":
        write_phase1(args.iters)
    elif args.cmd == "report":
        report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
