"""Bootstrap labels for the one-time fine-tune (spec 5.5).

1,600 abstracts: the gold seed set, 400 harvested negatives and the rest
stratified by hit strategy, year and MeSH organ group. With ANTHROPIC_API_KEY
present they are labelled by claude-sonnet-4-5; without one the build session
itself labels them, 25 abstracts per batch, straight to JSONL (spec 0.2).

  pixi run bootstrap prepare     # write data/labels/batches/batch_NNN.json
  pixi run bootstrap api         # label with the frontier model (needs the key)
  pixi run bootstrap ingest      # validate session-written labels into bootstrap.jsonl
  pixi run bootstrap split       # stratified 80/10/10 into data/train/*.jsonl
  pixi run bootstrap wandb       # log the table and the dataset artifact
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import re
from pathlib import Path

from pipeline import common as c
from pipeline import schema

TARGET_TOTAL = 1600
TARGET_NEGATIVES = 400
# How many MeSH-only papers to admit to the stratified pool (see select()).
MESH_ONLY_CAP = 250
BATCH_SIZE = 25
BATCH_DIR = c.LABELS / "batches"
SESSION_DIR = c.LABELS / "session"
BOOTSTRAP = c.LABELS / "bootstrap.jsonl"
SEED = 42

# Coarse organ grouping for stratification only (no LLM, no bearing on the tags).
ORGAN_PATTERNS = {
    "cardiovascular": r"cardio|heart|atheroscler|plaque|thrombo|platelet|vascul|endothel|hypertens",
    "respiratory": r"lung|pulmonar|airway|asthma|copd|respirator|alveol",
    "hematologic": r"blood|erythrocyt|h(a)?emat|h(a)?emoly|serum|plasma",
    "neuro_sleep": r"brain|neuro|cerebr|cognit|sleep|circadian|hippocamp|microglia",
    "gastrointestinal": r"intestin|gut|colon|colorect|bowel|microbiom|dysbios",
    "hepatorenal": r"liver|hepat|kidney|renal|nephro",
    "reproductive": r"placenta|pregnan|fetal|foetal|testis|sperm|ovar|reproduct",
    "metabolic_immune": r"metabol|obes|diabet|insulin|immun|inflammas|cytokin",
    "cancer": r"cancer|tumour|tumor|carcinom|neoplas|oncogen",
}


def organ_group(row) -> str:
    haystack = f"{row['title']} {row['mesh']}".lower()
    for group, pattern in ORGAN_PATTERNS.items():
        if re.search(pattern, haystack):
            return group
    return "other"


def strategy_bucket(hit: str) -> str:
    has_mesh, has_text = "mesh" in hit, "textword" in hit
    if "negative" in hit:
        return "negative"
    if has_mesh and has_text:
        return "both"
    return "mesh" if has_mesh else "textword"


def year_bucket(year) -> str:
    if not year:
        return "unknown"
    if year <= 2018:
        return "2004-2018"
    if year <= 2021:
        return "2019-2021"
    if year <= 2023:
        return "2022-2023"
    return "2024+"


def paper_record(row) -> dict:
    return {"pmid": row["pmid"], "title": row["title"], "journal": row["journal"],
            "year": row["year"], "mesh": row["mesh"], "abstract": row["abstract"],
            "pub_types": row["pub_types"]}


def select(conn) -> list[dict]:
    """Stratified selection of TARGET_TOTAL papers, deterministic under SEED."""
    rng = random.Random(SEED)
    rows = conn.execute(
        """SELECT pmid,title,journal,year,mesh,abstract,pub_types,hit_strategy,doi_status
           FROM papers WHERE abstract <> '' AND length(abstract) > 300""").fetchall()
    gold = {r[0] for r in conn.execute("SELECT pmid FROM gold_set WHERE pmid <> ''")}

    by_pmid = {r["pmid"]: r for r in rows}
    chosen: dict[str, str] = {}  # pmid -> why

    for pmid in gold:
        if pmid in by_pmid:
            chosen[pmid] = "gold"

    negatives = [r for r in rows if strategy_bucket(r["hit_strategy"]) == "negative"
                 and r["pmid"] not in chosen]
    rng.shuffle(negatives)
    for r in negatives[:TARGET_NEGATIVES]:
        chosen[r["pmid"]] = "negative"

    # Papers already labelled in an earlier pass stay in the selection, so a
    # rebalance never throws away labelling work.
    for path in sorted(SESSION_DIR.glob("*.jsonl")) if SESSION_DIR.exists() else []:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                pmid = str(json.loads(line).get("pmid", "")).strip()
            except json.JSONDecodeError:
                continue
            if pmid in by_pmid and pmid not in chosen:
                chosen[pmid] = "already_labelled"

    # Positives: verified DOIs first, then the rest, balanced across the
    # (strategy, year, organ) cells so no cell dominates the training set.
    #
    # The MeSH-only arm is largely bulk devices, drug carriers and laboratory
    # plasticware, which the tagger must reject but which teach it nothing about
    # assigning polymers, organs, pathways or rungs. It is capped so the label
    # budget goes mostly to the text-word arm, which is the genuine micro and
    # nanoplastic literature.
    pool = [r for r in rows if strategy_bucket(r["hit_strategy"]) != "negative"
            and r["pmid"] not in chosen]
    mesh_only = [r for r in pool if strategy_bucket(r["hit_strategy"]) == "mesh"]
    rng.shuffle(mesh_only)
    keep_mesh = {r["pmid"] for r in mesh_only[:MESH_ONLY_CAP]}
    pool = [r for r in pool if strategy_bucket(r["hit_strategy"]) != "mesh"
            or r["pmid"] in keep_mesh]
    cells: dict[tuple, list] = collections.defaultdict(list)
    for r in pool:
        cells[(strategy_bucket(r["hit_strategy"]), year_bucket(r["year"]), organ_group(r))].append(r)
    for key in cells:
        cells[key].sort(key=lambda r: (r["doi_status"] != "verified", rng.random()))

    remaining = TARGET_TOTAL - len(chosen)
    keys = sorted(cells.keys())
    rng.shuffle(keys)
    cursor = {k: 0 for k in keys}
    while remaining > 0 and any(cursor[k] < len(cells[k]) for k in keys):
        for key in keys:
            if remaining <= 0:
                break
            idx = cursor[key]
            if idx < len(cells[key]):
                row = cells[key][idx]
                cursor[key] += 1
                chosen[row["pmid"]] = "stratified:" + ":".join(key)
                remaining -= 1

    out = []
    for pmid, why in chosen.items():
        rec = paper_record(by_pmid[pmid])
        rec["selection"] = why
        out.append(rec)
    out.sort(key=lambda r: r["pmid"])
    return out


def already_labelled() -> set[str]:
    """PMIDs that already carry a label in data/labels/session/."""
    out: set[str] = set()
    if not SESSION_DIR.exists():
        return out
    for path in SESSION_DIR.glob("*.jsonl"):
        for line in path.read_text().splitlines():
            if line.strip():
                try:
                    out.add(str(json.loads(line).get("pmid", "")).strip())
                except json.JSONDecodeError:
                    continue
    return out - {""}


def prepare() -> None:
    conn = c.connect()
    selected = select(conn)
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    for old in BATCH_DIR.glob("batch_*.json"):
        old.unlink()

    c.jsonl_write(c.LABELS / "selection.jsonl", selected)
    # Batches hold only papers that still need a label, so a re-prepare after a
    # rebalance never asks for work that is already done.
    labelled = already_labelled()
    todo = [r for r in selected if r["pmid"] not in labelled]
    # In-scope papers first: the text-word arm and the gold set carry the whole
    # tagging task (polymer, organ, pathway, rung), while the MeSH-only arm and the
    # harvested negatives are mostly straightforward rejections. Labelling the hard
    # part first means a budget cut costs the easy examples, not the useful ones.
    priority = {"gold": 0, "stratified:both": 1, "stratified:textword": 1,
                "stratified:mesh": 2, "negative": 3}
    todo.sort(key=lambda r: (priority.get(":".join(r["selection"].split(":")[:2]), 2),
                             r["pmid"]))
    for i in range(0, len(todo), BATCH_SIZE):
        batch = todo[i:i + BATCH_SIZE]
        n = i // BATCH_SIZE + 1
        payload = [{"pmid": r["pmid"], "title": r["title"],
                    "journal": f"{r['journal']} ({r['year'] or '?'})",
                    "pub_types": r["pub_types"][:120],
                    "mesh": (r["mesh"] or "")[:400],
                    "abstract": (r["abstract"] or "")[:2400]} for r in batch]
        (BATCH_DIR / f"batch_{n:03d}.json").write_text(
            json.dumps(payload, indent=1, ensure_ascii=False))

    counts = collections.Counter(r["selection"].split(":")[0] for r in selected)
    c.log(f"bootstrap prepare: {len(selected)} papers selected, {len(labelled)} already "
          f"labelled, {len(todo)} to label in "
          f"{(len(todo) + BATCH_SIZE - 1) // BATCH_SIZE} batches, mix {dict(counts)}")
    (c.LABELS / "PROMPT.md").write_text(
        "# Bootstrap labelling prompt\n\n## System\n\n" + schema.SYSTEM_PROMPT +
        "\n\n## Instructions\n\n" + schema.LABEL_INSTRUCTIONS + "\n")


# ------------------------------------------------------------------- frontier model

def api_label() -> None:
    """Label every prepared batch with claude-sonnet-4-5 (spec 5.5)."""
    key = c.api_key("ANTHROPIC_API_KEY")
    if not key:
        c.log("bootstrap api: no ANTHROPIC_API_KEY; the build session labels the batches instead")
        return
    import anthropic  # imported lazily: only needed on the API path

    client = anthropic.Anthropic(api_key=key)
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(BATCH_DIR.glob("batch_*.json")):
        out_path = SESSION_DIR / f"{path.stem}.jsonl"
        if out_path.exists():
            continue
        papers = json.loads(path.read_text())
        body = "\n\n".join(
            f"### {p['pmid']}\nTITLE: {p['title']}\nJOURNAL: {p['journal']}\n"
            f"TYPES: {p['pub_types']}\nMESH: {p['mesh']}\nABSTRACT: {p['abstract']}"
            for p in papers)
        message = client.messages.create(
            model="claude-sonnet-4-5", max_tokens=8000,
            system=schema.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": schema.LABEL_INSTRUCTIONS +
                       "\n\nLabel each article below. Return one JSON object per line, "
                       "each with an extra \"pmid\" field, in the same order.\n\n" + body}])
        text = "".join(b.text for b in message.content if b.type == "text")
        lines = [ln for ln in text.splitlines() if ln.strip().startswith("{")]
        out_path.write_text("\n".join(lines) + "\n")
        c.log(f"bootstrap api: {path.stem} -> {len(lines)} labels")


# -------------------------------------------------------------------------- ingest

def ingest() -> None:
    """Validate every session or API label and merge into bootstrap.jsonl."""
    selection = {r["pmid"]: r for r in c.jsonl_read(c.LABELS / "selection.jsonl")}
    labels: dict[str, dict] = {}
    problems: list[str] = []
    candidates: collections.Counter = collections.Counter()

    for path in sorted(SESSION_DIR.glob("*.jsonl")):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            raw = schema.extract_json(line)
            if raw is None:
                problems.append(f"{path.name}:{lineno} unparseable")
                continue
            pmid = str(raw.pop("pmid", "")).strip()
            if pmid not in selection:
                problems.append(f"{path.name}:{lineno} pmid {pmid!r} not in the selection")
                continue
            tag, probs, cands = schema.validate(raw)
            if tag is None:
                problems.append(f"{path.name}:{lineno} {pmid} invalid: {probs}")
                continue
            for field, value in cands:
                candidates[(field, value)] += 1
            labels[pmid] = tag

    records = []
    for pmid, tag in sorted(labels.items()):
        paper = selection[pmid]
        records.append({"pmid": pmid, "paper": paper, "tag": tag})
    c.jsonl_write(BOOTSTRAP, records)

    conn = c.connect()
    with conn:
        conn.executemany(
            """INSERT INTO vocab_candidates (field,value,count,first_seen) VALUES (?,?,?,?)
               ON CONFLICT(field,value) DO UPDATE SET count=vocab_candidates.count+excluded.count""",
            [(f, v, n, c.now()) for (f, v), n in candidates.items()])

    relevant = sum(1 for r in records if r["tag"]["relevant"])
    c.log(f"bootstrap ingest: {len(records)}/{len(selection)} labelled "
          f"({relevant} relevant, {len(records) - relevant} not), "
          f"{len(problems)} problems, {len(candidates)} vocabulary candidates")
    if problems:
        (c.LABELS / "ingest_problems.txt").write_text("\n".join(problems[:500]) + "\n")


# --------------------------------------------------------------------------- split

def split() -> None:
    """Stratified 80/10/10 on (relevant, model_type), written in mlx chat format."""
    records = list(c.jsonl_read(BOOTSTRAP))
    if not records:
        raise SystemExit("no bootstrap labels: run ingest first")
    rng = random.Random(SEED)
    strata: dict[tuple, list] = collections.defaultdict(list)
    for r in records:
        strata[(r["tag"]["relevant"], r["tag"]["model_type"])].append(r)

    train, valid, test = [], [], []
    for key in sorted(strata, key=str):
        group = strata[key]
        rng.shuffle(group)
        n = len(group)
        n_valid = max(1, round(n * 0.1)) if n >= 10 else (1 if n >= 3 else 0)
        n_test = max(1, round(n * 0.1)) if n >= 10 else (1 if n >= 2 else 0)
        valid.extend(group[:n_valid])
        test.extend(group[n_valid:n_valid + n_test])
        train.extend(group[n_valid + n_test:])

    for name, rows in (("train", train), ("valid", valid), ("test", test)):
        rng.shuffle(rows)
        chat = [{"messages": [
            {"role": "system", "content": schema.SYSTEM_PROMPT},
            {"role": "user", "content": schema.user_prompt(r["paper"])},
            {"role": "assistant", "content": json.dumps(r["tag"], separators=(",", ":"),
                                                        ensure_ascii=False)}]} for rows_ in [rows] for r in rows_]
        c.jsonl_write(c.TRAIN / f"{name}.jsonl", chat)
        # The paper and tag alongside, so the test split can be scored by field.
        c.jsonl_write(c.TRAIN / f"{name}_meta.jsonl", rows)
    c.log(f"bootstrap split: train {len(train)}, valid {len(valid)}, test {len(test)}")


# --------------------------------------------------------------------------- wandb

def log_wandb() -> None:
    import os

    import wandb

    cfg = c.load_toml("wandb.toml")
    if not c.api_key("WANDB_API_KEY"):
        os.environ["WANDB_MODE"] = "offline"
        c.log("bootstrap wandb: no WANDB_API_KEY; WANDB_MODE=offline")
    run = wandb.init(project=cfg.get("project", "debris"),
                     entity=cfg.get("entity") or None,
                     job_type="dataset", name="bootstrap-labels",
                     dir=str(c.ROOT), config={"target_total": TARGET_TOTAL,
                                              "negatives": TARGET_NEGATIVES, "seed": SEED})
    records = list(c.jsonl_read(BOOTSTRAP))
    table = wandb.Table(columns=["pmid", "title", "journal", "year", "relevant", "polymers",
                                 "organ_systems", "disease_categories", "pathways",
                                 "model_type", "rungs", "pet_specific", "confidence", "summary"])
    for r in records:
        t, p = r["tag"], r["paper"]
        table.add_data(r["pmid"], p["title"][:200], p["journal"], p["year"], t["relevant"],
                       ",".join(t["polymers"]), ",".join(t["organ_systems"]),
                       ",".join(t["disease_categories"]), ",".join(t["pathways"]),
                       t["model_type"], ",".join(map(str, t["evidence_rungs"])),
                       t["pet_specific"], t["confidence"], t["summary"])
    run.log({"bootstrap_labels": table})
    artifact = wandb.Artifact(cfg.get("dataset_artifact", "debris-train"), type="dataset",
                              description="DEBRIS bootstrap labels, stratified 80/10/10")
    for name in ("train", "valid", "test"):
        artifact.add_file(str(c.TRAIN / f"{name}.jsonl"))
        artifact.add_file(str(c.TRAIN / f"{name}_meta.jsonl"))
    artifact.add_file(str(c.CONFIG / "vocab.toml"))
    artifact.add_file(str(c.LABELS / "PROMPT.md"))
    run.log_artifact(artifact)
    url = getattr(run, "url", None) or "offline"
    run.finish()
    c.log(f"bootstrap wandb: logged {len(records)} labels, artifact "
          f"{cfg.get('dataset_artifact', 'debris-train')}, run {url}")
    Path(c.ROOT / "GATE_NOTES.md").write_text(
        "# Notes (informational, not gates)\n\n"
        "## wandb\n\n"
        f"Runs were recorded locally under `wandb/` because WANDB_API_KEY was absent.\n"
        f"To push them when a key is available:\n\n```bash\nexport WANDB_API_KEY=...\n"
        f"cd {c.ROOT}\nwandb sync wandb/offline-run-*\n```\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="DEBRIS bootstrap labels")
    ap.add_argument("stage", choices=["prepare", "api", "ingest", "split", "wandb", "all"])
    args = ap.parse_args()
    if args.stage in ("prepare", "all"):
        prepare()
    if args.stage in ("api", "all"):
        api_label()
    if args.stage in ("ingest", "all"):
        ingest()
    if args.stage in ("split", "all"):
        split()
    if args.stage in ("wandb", "all"):
        log_wandb()


if __name__ == "__main__":
    main()
