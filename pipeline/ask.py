"""DEBRIS LLM (tab 06, D69): answers to the fill-the-sentence question builder.

The question is built from three fixed choices (a plastic, a part of the body, a rung of
the evidence ladder), so there are 6 x 9 x 6 = 324 questions and every answer can be
written offline, after the weekly run, instead of by a model at request time.

Each answer has two parts:
* the lead: one sentence with the paper count, written from a template, so every number
  shown comes from the database;
* the reading: one or two sentences a language model writes from the summaries of the
  papers listed under the answer. It is checked before it is kept (no causal claims about
  people, no figures that are not in its input, house style), and an answer whose input
  has changed since it was written is not shown until it is rewritten.

  pixi run python -m pipeline.ask --local     # write missing or stale readings (Studio)
  pixi run python -m pipeline.ask --check     # count what is missing, write nothing

The model comes from config/tuning.toml [ask]. Without a model the tab shows the leads
and the paper lists only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time

from pipeline import common as c

PLASTICS = [
    {"k": "ANY", "l": "any plastic", "name": "microplastics"},
    {"k": "PS", "l": "polystyrene (PS)", "name": "polystyrene"},
    {"k": "PE", "l": "polyethylene (PE)", "name": "polyethylene"},
    {"k": "PP", "l": "polypropylene (PP)", "name": "polypropylene"},
    {"k": "PET", "l": "PET", "name": "PET"},
    {"k": "PVC", "l": "PVC", "name": "PVC"},
]
PLACES = [
    {"k": "gastrointestinal", "l": "the gut"},
    {"k": "neurological", "l": "the brain and nerves"},
    {"k": "respiratory", "l": "the lungs"},
    {"k": "cardiovascular", "l": "the heart and blood vessels"},
    {"k": "hepatic", "l": "the liver"},
    {"k": "renal", "l": "the kidneys"},
    {"k": "reproductive_placental", "l": "reproduction and pregnancy"},
    {"k": "immune", "l": "the immune system"},
    {"k": "endocrine_metabolic", "l": "hormones and metabolism"},
]
QUESTIONS = [
    {"r": 1, "l": "found in people", "short": "In people"},
    {"r": 2, "l": "linked to health in people", "short": "Linked"},
    {"r": 3, "l": "what happens in animals", "short": "Animals"},
    {"r": 4, "l": "how it might act", "short": "Mechanism"},
    {"r": 5, "l": "whether more means worse", "short": "Dose"},
    {"r": 6, "l": "whether harm reverses", "short": "Reverses"},
]
PAPERS_SHOWN = 3     # listed under each answer, and all the model reads
PATHS_SHOWN = 3
MAX_WORDS = 60

SYSTEM = (
    "You write one or two plain sentences for a public website about research on micro and "
    "nanoplastics in human disease. You are given a question and the one-line summaries of up "
    "to three papers. Say what those papers report, in British English, for a general reader. "
    "Use only facts in the summaries. Do not give advice. Never say that plastics cause, lead "
    "to or are responsible for disease or harm in people: findings in people are associations "
    "or detections. Findings in animals or cells must be described as being in animals or "
    "cells. No em dashes, no lists, no headings, no citations, at most 60 words.")

# A reading is dropped (and the tab shows the lead alone) when it matches any of these.
CAUSAL = re.compile(r"\b(caus(e|es|ed|ing)|leads? to|led to|responsible for|results? in|"
                    r"triggers?|proves?|proven)\b", re.I)
BANNED = re.compile(r"\b(groundbreaking|revolutionary|paradigm-shifting|game-changing|"
                    r"cutting-edge|unprecedented|seamless|leverag(e|es|ing)|delve)\b|—", re.I)


def key(po: str, pl: str, r: int) -> str:
    return f"{po}|{pl}|{r}"


def cube(conn) -> dict:
    """Per plastic and part of the body: the total, the papers per rung (newest first, the
    first few with their summaries) and the commonest mechanisms."""
    corpus = c.corpus_clause()
    labels = c.display_vocab()["pathway_labels"]
    out = {}
    for po in PLASTICS:
        pf = "" if po["k"] == "ANY" else \
            "AND p.pmid IN (SELECT pmid FROM tag_polymers WHERE polymer = :po)"
        for pl in PLACES:
            args = {"po": po["k"], "pl": pl["k"]}
            base = f"""FROM papers p JOIN tags t USING (pmid)
                       WHERE {corpus} AND t.relevant = 1 {pf}
                         AND p.pmid IN (SELECT pmid FROM tag_organs WHERE organ_system = :pl)"""
            total = conn.execute(f"SELECT COUNT(*) {base}", args).fetchone()[0]
            rungs = {}
            for q in QUESTIONS:
                rb = f"{base} AND p.pmid IN (SELECT pmid FROM tag_rungs WHERE rung = {q['r']})"
                n = conn.execute(f"SELECT COUNT(*) {rb}", args).fetchone()[0]
                papers = [dict(r) for r in conn.execute(f"""
                    SELECT p.pmid, p.title, p.journal, p.year, t.summary {rb}
                    ORDER BY p.year DESC, t.confidence DESC, p.pmid LIMIT {PAPERS_SHOWN}""", args)]
                rungs[q["r"]] = {"n": n, "papers": papers}
            paths = [[labels.get(k, k), n] for k, n in conn.execute(f"""
                SELECT pathway, COUNT(*) FROM tag_pathways
                WHERE pathway NOT LIKE 'other%' AND pmid IN (SELECT p.pmid {base})
                GROUP BY pathway ORDER BY COUNT(*) DESC, pathway LIMIT {PATHS_SHOWN}""", args)]
            out[f"{po['k']}|{pl['k']}"] = {"total": total, "rungs": rungs, "paths": paths}
    return out


def lead(po: dict, pl: dict, r: int, n: int) -> str:
    """The counted sentence. Every figure in it is a database count."""
    p, a, one = po["name"], pl["l"], n == 1
    if not n:
        return {1: f"No paper in DEBRIS yet detects {p} in people while studying {a}.",
                2: f"No paper in DEBRIS yet links {p} to a health measure in people for {a}.",
                3: f"No animal study of {p} and {a} is in DEBRIS yet.",
                4: f"No paper in DEBRIS yet looks at how {p} acts on {a}.",
                5: f"No dose-response study of {p} and {a} is in DEBRIS yet.",
                6: f"No paper in DEBRIS yet tests whether effects of {p} on {a} reverse."}[r]
    papers = f"{n:,} {'paper' if one else 'papers'}"
    return {1: f"{papers} on {a} {'detects' if one else 'detect'} {p} in people.",
            2: f"{papers} on {a} {'links' if one else 'link'} {p} to a health measure in people.",
            3: f"{papers} {'tests' if one else 'test'} {p} in animals, looking at {a}.",
            4: f"{papers} {'looks' if one else 'look'} at how {p} acts on cells or tissue of {a}.",
            5: f"{papers} on {a} {'finds' if one else 'find'} bigger effects at higher doses of {p}.",
            6: f"{papers} on {a} {'tests' if one else 'test'} whether effects of {p} reverse "
               f"once exposure stops."}[r]


def prompt(po: dict, pl: dict, q: dict, papers: list[dict]) -> str:
    lines = [f"Question: {po['name']} and {pl['l']}: {q['l']}.", "Papers:"]
    lines += [f"- {p['title']} ({p['year']}). Summary: {p['summary'] or 'none'}" for p in papers]
    lines.append("Write what these papers report.")
    return "\n".join(lines)


def input_hash(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def check(reading: str, source: str) -> tuple[str | None, str]:
    """The reading as it will be shown, or None with the reason it was dropped."""
    text = re.sub(r"\s+", " ", reading or "").strip().strip('"')
    if not text:
        return None, "empty"
    if CAUSAL.search(text):
        return None, "causal wording"
    if BANNED.search(text):
        return None, "house style"
    if len(text.split()) > MAX_WORDS:
        return None, "too long"
    stray = set(re.findall(r"\d+(?:\.\d+)?", text)) - set(re.findall(r"\d+(?:\.\d+)?", source))
    if stray:
        return None, f"figures not in the input: {', '.join(sorted(stray))}"
    return text, "ok"


def jobs(conn) -> list[dict]:
    """Every question with papers behind it, with its prompt and that prompt's hash."""
    data = cube(conn)
    out = []
    for po in PLASTICS:
        for pl in PLACES:
            cell = data[f"{po['k']}|{pl['k']}"]
            for q in QUESTIONS:
                papers = cell["rungs"][q["r"]]["papers"]
                if not papers:
                    continue
                text = prompt(po, pl, q, papers)
                out.append({"key": key(po["k"], pl["k"], q["r"]), "prompt": text,
                            "hash": input_hash(text)})
    return out


def stored(conn) -> dict[str, dict]:
    return {r["key"]: dict(r) for r in conn.execute("SELECT * FROM ask_answers")}


def write(conn, todo: list[dict], cfg: dict) -> dict:
    """Write readings with the local mlx model, in batches, keeping only those that pass."""
    from mlx_lm import load

    from pipeline.tag import generate_many

    model, tokenizer = load(cfg["model"])
    counts = {"kept": 0, "dropped": 0}
    batch = int(cfg.get("batch_size", 16))
    for start in range(0, len(todo), batch):
        chunk = todo[start:start + batch]
        answers = generate_many(model, tokenizer, [j["prompt"] for j in chunk], batch,
                                system=SYSTEM)
        with conn:
            for job, (raw, _) in zip(chunk, answers):
                text, why = check(raw, job["prompt"])
                counts["kept" if text else "dropped"] += 1
                conn.execute("""INSERT INTO ask_answers (key, input_hash, reading, status, model, written_at)
                                VALUES (?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET
                                input_hash=excluded.input_hash, reading=excluded.reading,
                                status=excluded.status, model=excluded.model,
                                written_at=excluded.written_at""",
                             (job["key"], job["hash"], text, why, cfg["model"], c.now()))
        print(f"  ask: {start + len(chunk)}/{len(todo)} written", flush=True)
    return counts


def bundle(conn) -> dict:
    """What the tab reads: the choices, and per question the lead, the reading (only when
    it was written from the papers now listed), the counts and the papers."""
    data = cube(conn)
    have = stored(conn)
    answers = {}
    for po in PLASTICS:
        for pl in PLACES:
            cell = data[f"{po['k']}|{pl['k']}"]
            for q in QUESTIONS:
                x = cell["rungs"][q["r"]]
                k = key(po["k"], pl["k"], q["r"])
                reading = None
                if x["papers"]:
                    row = have.get(k)
                    h = input_hash(prompt(po, pl, q, x["papers"]))
                    if row and row["input_hash"] == h and row["reading"]:
                        reading = row["reading"]
                answers[k] = {"n": x["n"], "lead": lead(po, pl, q["r"], x["n"]), "reading": reading,
                              "papers": [[p["pmid"], p["title"], p["journal"], p["year"]]
                                         for p in x["papers"]]}
    totals = {k: {"total": v["total"], "paths": v["paths"],
                  "ladder": [v["rungs"][q["r"]]["n"] for q in QUESTIONS]} for k, v in data.items()}
    model = c.tuning().get("ask", {}).get("model")
    return {"plastics": PLASTICS, "places": PLACES, "questions": QUESTIONS,
            "cells": totals, "answers": answers, "model": model,
            "written": sum(1 for a in answers.values() if a["reading"])}


def main() -> int:
    ap = argparse.ArgumentParser(description="Write the DEBRIS LLM answers")
    ap.add_argument("--local", action="store_true", help="write with the local mlx model")
    ap.add_argument("--check", action="store_true", help="report what is missing, write nothing")
    ap.add_argument("--force", action="store_true", help="rewrite every answer")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    c.init_db()
    conn = c.connect()
    have = stored(conn)
    all_jobs = jobs(conn)
    todo = [j for j in all_jobs if args.force or have.get(j["key"], {}).get("input_hash") != j["hash"]]
    if args.limit:
        todo = todo[:args.limit]
    c.log(f"ask: {len(all_jobs)} questions with papers, {len(todo)} to write")
    if args.check or not todo:
        return 0
    if not args.local:
        c.log("ask: no model chosen (--local); the tab shows leads and papers until one runs")
        return 0
    cfg = c.tuning().get("ask", {})
    if not cfg.get("model"):
        c.log("ask: no [ask] model in config/tuning.toml; skipped")
        return 0
    started = time.monotonic()
    counts = write(conn, todo, cfg)
    c.log(f"ask: kept {counts['kept']}, dropped {counts['dropped']} by the checks, "
          f"{(time.monotonic() - started) / 60:.1f} min with {cfg['model']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
