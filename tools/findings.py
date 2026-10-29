"""FINDINGS.md, generated from the database (spec 6, item 6).

Everything here is read out of `data/debris.sqlite`, `data/train/metrics.json` and the
timer definitions, so the numbers in the document are the numbers the app is serving.
Drift recommendations appended by `pipeline/drift.py` are preserved on regeneration.

  pixi run findings
"""
from __future__ import annotations

import collections
import json
import plistlib
import re
from datetime import date, datetime, timedelta

from pipeline import aggregate as agg
from pipeline import common as c

V = c.vocab()
DRIFT_MARKER = "## Drift recommendation"
STRATEGIES = {"mesh": "A, MeSH terms", "textword": "B, title and abstract words",
              "negative": "Negative controls"}


def fmt(n: int | float) -> str:
    return f"{n:,}" if isinstance(n, int) else f"{n:.2f}"


def table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return "\n".join(out)


# --------------------------------------------------------------------- sections

def corpus_section(conn) -> str:
    rows = conn.execute("SELECT hit_strategy, COUNT(*) n FROM papers GROUP BY 1").fetchall()
    hits: collections.Counter = collections.Counter()
    for row in rows:
        for part in (row["hit_strategy"] or "unknown").split(","):
            hits[part] += row["n"]
    overlap = next((r["n"] for r in rows if r["hit_strategy"] == "mesh,textword"), 0)
    total = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]

    strategy = table(["Strategy", "PMIDs"],
                     [[label, fmt(hits.get(key, 0))] for key, label in STRATEGIES.items()]
                     + [["Found by both A and B", fmt(overlap)],
                        ["**Union harvested**", f"**{fmt(total)}**"]])

    years = conn.execute("""SELECT year, COUNT(*) n,
                                   SUM(CASE WHEN doi_status='verified' THEN 1 ELSE 0 END) v
                            FROM papers WHERE year IS NOT NULL GROUP BY year
                            ORDER BY year DESC LIMIT 12""").fetchall()
    by_year = table(["Year", "Harvested", "DOI verified"],
                    [[r["year"], fmt(r["n"]), fmt(r["v"] or 0)] for r in years])
    earliest = conn.execute("SELECT MIN(year) FROM papers WHERE year > 0").fetchone()[0]
    return (f"## Corpus\n\nTwo PubMed strategies, unioned, each PMID keeping the strategies "
            f"that found it. `PET[tiab]` is never searched on its own, because it returns "
            f"positron emission tomography.\n\n{strategy}\n\n"
            f"### By year\n\nThe twelve most recent years; the corpus reaches back to "
            f"{earliest}.\n\n{by_year}\n")


def funnel_section(conn) -> str:
    rows = conn.execute("""SELECT doi_status, COUNT(*) n, SUM(retracted) r
                           FROM papers GROUP BY 1 ORDER BY n DESC""").fetchall()
    total = sum(r["n"] for r in rows)
    body = table(["DOI status", "Papers", "Share", "Retracted"],
                 [[r["doi_status"], fmt(r["n"]), f"{r['n'] / total:.1%}", fmt(r["r"] or 0)]
                  for r in rows])
    no_abstract = conn.execute("SELECT COUNT(*) FROM papers WHERE abstract = ''").fetchone()[0]
    verified = conn.execute(
        "SELECT COUNT(*) FROM papers WHERE doi_status='verified'").fetchone()[0]
    retracted = conn.execute("SELECT COUNT(*) FROM papers WHERE retracted = 1").fetchone()[0]
    controls = conn.execute(f"""SELECT COUNT(*) FROM papers WHERE doi_status = 'verified'
                                AND COALESCE(hit_strategy, '') = '{c.CORPUS_STRATEGY}'"""
                            ).fetchone()[0]
    return (f"## Verification funnel\n\nA paper is admitted when Crossref resolves its DOI "
            f"and `token_set_ratio` between the PubMed and Crossref titles, case-folded, "
            f"is at least 90. Only verified papers are counted in the charts; the Papers "
            f"tab has an \"include unverified\" switch, off by default.\n\n{body}\n\n"
            f"{fmt(verified)} papers are verified. {fmt(controls)} of those were harvested "
            f"on purpose as negative controls, positron emission tomography and CT work "
            f"above all, so that the tagger can be shown refusing them; they are not part "
            f"of the corpus and are excluded from every count the site publishes, which "
            f"leaves {fmt(verified - controls)}. {fmt(no_abstract)} have no abstract, so "
            f"they are stored but never tagged. {fmt(retracted)} are flagged retracted by a "
            f"Crossref `update-to` relation: they are struck through in the app and never "
            f"deleted.\n")


def tagger_section() -> str:
    path = c.TRAIN / "metrics.json"
    if not path.exists():
        return ("## Tagger\n\nThe tagger has not been scored yet; see `MODEL_CARD.md` once "
                "`pixi run train` has finished.\n")
    data = json.loads(path.read_text())
    fused, q4, floor = data["fused"], data.get("q4"), data["floor"]
    rows = []
    for field, value in fused.items():
        if field in floor:
            rows.append([f"`{field}`", value, floor[field],
                         "yes" if value >= floor[field] else "**no**",
                         q4.get(field, "") if q4 else ""])
    body = table(["Field", "Fused", "Floor", "Meets floor", "q4"], rows)
    shortfall = data.get("shortfall") or []
    verdict = ("Every acceptance floor in spec 5.5 is met." if not shortfall
               else "Below floor: " + "; ".join(shortfall) + ".")
    curve = data.get("curve") or []
    losses = [p for p in curve if "val_loss" in p]
    curve_line = (f"Validation loss ran {losses[0]['val_loss']} to {losses[-1]['val_loss']} "
                  f"over {losses[-1]['iter']} iterations. " if len(losses) > 1 else "")
    return (f"## Tagger\n\n`debris_v1` is a single LoRA fine-tune of "
            f"`Qwen/Qwen2.5-3B-Instruct`, trained once on the task and the schema rather "
            f"than on facts. The weekly refresh never retrains it. {curve_line}"
            f"Scored on the held-out split of {fused['n']} papers, which no training or "
            f"validation step saw.\n\n{body}\n\n{verdict} Full card in `MODEL_CARD.md`; the "
            f"run and its loss curve are in wandb (offline under `wandb/` while no API key "
            f"is set).\n")


def organ_section(conn) -> str:
    rows = conn.execute("""SELECT o.organ_system AS organ, COUNT(DISTINCT p.pmid) n,
                                  SUM(CASE WHEN t.pet_specific=1 THEN 1 ELSE 0 END) pet
                           FROM papers p JOIN tags t USING (pmid)
                           JOIN tag_organs o ON o.pmid = p.pmid
                           WHERE p.doi_status='verified' AND t.relevant=1
                           GROUP BY 1 ORDER BY n DESC""").fetchall()
    if not rows:
        return "## PET share by organ system\n\nNo papers are tagged yet.\n"
    labels = V.get("organ_labels", {})
    body = table(["Organ system", "Relevant papers", "PET specific", "PET share"],
                 [[labels.get(r["organ"], r["organ"]), fmt(r["n"]), fmt(r["pet"] or 0),
                   f"{(r['pet'] or 0) / r['n']:.0%}"] for r in rows])
    return (f"## PET share by organ system\n\n\"PET specific\" means the paper names "
            f"polyethylene terephthalate, not that PET is the only polymer it studied. A "
            f"paper counts once per organ system it reports.\n\n{body}\n")


def pathway_section(conn) -> str:
    rows = conn.execute("""SELECT w.pathway AS pathway, COUNT(DISTINCT p.pmid) n,
                                  MAX(r.rung) top_rung
                           FROM papers p JOIN tags t USING (pmid)
                           JOIN tag_pathways w ON w.pmid = p.pmid
                           LEFT JOIN tag_rungs r ON r.pmid = p.pmid
                           WHERE p.doi_status='verified' AND t.relevant=1
                           GROUP BY 1 ORDER BY n DESC LIMIT 12""").fetchall()
    if not rows:
        return "## Pathways\n\nNo papers are tagged yet.\n"
    labels = V.get("pathway_labels", {})
    rungs = {r["rung"]: r["label"] for r in V["rungs"]}
    body = table(["Pathway", "Papers", "Highest rung reached"],
                 [[labels.get(r["pathway"], r["pathway"]), fmt(r["n"]),
                   f"{r['top_rung']}, {rungs.get(r['top_rung'], 'none')}"
                   if r["top_rung"] else "not scored"] for r in rows])
    return (f"## Pathways\n\nThe twelve most reported mechanisms among relevant papers, with "
            f"the highest evidence rung any one of those papers reaches. A high rung on a "
            f"busy pathway is not a causal claim: it records how close to a human outcome "
            f"the strongest single study sits.\n\n{body}\n")


def gold_section(conn) -> str:
    rows = conn.execute("""SELECT g.key, g.pmid, g.title, g.expect, t.relevant,
                                  t.pet_specific, t.model_type, t.confidence
                           FROM gold_set g LEFT JOIN tags t USING (pmid)
                           WHERE g.pmid <> '' ORDER BY g.key""").fetchall()
    if not rows:
        return "## Gold controls\n\nThe gold set is empty.\n"
    out = []
    for r in rows:
        polymers = [x[0] for x in conn.execute(
            "SELECT polymer FROM tag_polymers WHERE pmid=? ORDER BY polymer", (r["pmid"],))]
        organs = [x[0] for x in conn.execute(
            "SELECT organ_system FROM tag_organs WHERE pmid=? ORDER BY organ_system",
            (r["pmid"],))]
        rungs = [str(x[0]) for x in conn.execute(
            "SELECT rung FROM tag_rungs WHERE pmid=? ORDER BY rung", (r["pmid"],))]
        out.append([f"`{r['key']}`", r["pmid"],
                    "not tagged" if r["relevant"] is None
                    else ("relevant" if r["relevant"] else "**not relevant**"),
                    ", ".join(polymers) or "none",
                    ", ".join(organs) or "none",
                    ", ".join(rungs) or "none",
                    "yes" if r["pet_specific"] else "no",
                    f"{r['confidence']:.2f}" if r["confidence"] is not None else "-"])
    body = table(["Control", "PMID", "Relevance", "Polymers", "Organ systems", "Rungs",
                  "PET", "Confidence"], out)
    return (f"## Gold controls\n\nNine papers chosen before the tagger existed, each with an "
            f"expected outcome. They are tagged by the same pass as everything else, so this "
            f"table is a standing check that the headline papers are still found and still "
            f"read correctly.\n\n{body}\n")


def vocabulary_section(conn) -> str:
    rows = conn.execute("""SELECT field, value, count FROM vocab_candidates
                           ORDER BY count DESC, value LIMIT 25""").fetchall()
    if not rows:
        return ("## Vocabulary candidates\n\nNo out-of-vocabulary values have been "
                "proposed.\n")
    body = table(["Field", "Proposed value", "Papers"],
                 [[r["field"], f"`{r['value'].removeprefix('other:')}`", fmt(r["count"])]
                  for r in rows])
    return (f"## Vocabulary candidates\n\nWhen the tagger reaches for a term the controlled "
            f"vocabulary does not hold, it records `other:<term>` and the paper goes to the "
            f"review queue rather than being published with an invented tag. The Venn, body "
            f"map and pathway hub are fixed on the vocabulary in `config/vocab.toml`, so "
            f"adding any of these is a human decision, not something the pipeline does on "
            f"its own.\n\n{body}\n")


def gaps_section(conn) -> str:
    # The same population the Atlas Venn draws from, so the counts match the chart.
    pmids = agg.verified_pmids(conn)
    if not conn.execute("SELECT COUNT(*) FROM tag_polymers").fetchone()[0]:
        return "## Research gaps\n\nNo papers are tagged yet.\n"
    polymers = agg.polymer_map(conn)
    counts = agg.venn_counts(pmids, polymers, agg.MAIN_SETS)
    names = [name for name, _ in agg.MAIN_SETS]
    regions = []
    for bits in range(1, 1 << len(names)):
        code = "".join("1" if bits >> (len(names) - 1 - i) & 1 else "0"
                       for i in range(len(names)))
        inside = [names[i] for i, ch in enumerate(code) if ch == "1"]
        outside = [names[i] for i, ch in enumerate(code) if ch == "0"]
        label = " and ".join(inside) + (f", not {' or '.join(outside)}" if outside else "")
        regions.append((counts.get(code, 0), label, code))
    regions.sort()
    emptiest = regions[:3]
    body = table(["Venn region", "Papers"], [[label, fmt(n)] for n, label, _ in emptiest])
    lines = []
    for n, label, code in emptiest:
        members = [names[i] for i, ch in enumerate(code) if ch == "1"]
        lines.append(f"- **{label}** holds {fmt(n)} "
                     f"{'paper' if n == 1 else 'papers'}. Nothing yet compares "
                     f"{' with '.join(members)} in that combination against a shared "
                     f"endpoint.")
    return (f"## Research gaps\n\nThe three emptiest regions of the polymer Venn, offered as "
            f"starting points for the workshop. An empty region is an absence of published "
            f"work, not evidence of safety.\n\n{body}\n\n" + "\n".join(lines) + "\n")


def operations_section(conn) -> str:
    run = conn.execute("""SELECT run_id, finished_at, model_version, inference_path, harvested,
                                 verified, tagged, queued, novel FROM ingest_runs
                          ORDER BY started_at DESC LIMIT 1""").fetchone()
    if run and run["inference_path"]:
        path = {"studio_mlx": "B, the mlx model on the Studio",
                "zerogpu_space": "A, the Hugging Face ZeroGPU Space"}.get(
                    run["inference_path"], run["inference_path"])
    else:
        path = ("B, the mlx model on the Studio (no HF_TOKEN present)"
                if not c.api_key("HF_TOKEN") else "A, the Hugging Face ZeroGPU Space")
    rows = [["Inference path", path],
            ["Model version", (run["model_version"] if run else None) or "debris_v1"],
            ["Weights", "`data/adapters/debris_v1_fused`"
             if (c.ROOT / "USE_FUSED").exists() else "`data/adapters/debris_v1_q4`"],
            ["Next scheduled run", next_run()],
            ["Review queue", fmt(conn.execute(
                "SELECT COUNT(*) FROM review_queue WHERE resolved_at IS NULL").fetchone()[0])]]
    if run:
        rows.append(["Last run", f"`{run['run_id']}`, {run['finished_at'] or 'in progress'}"])
    return (f"## Operations\n\n{table(['', ''], rows)}\n\nThe refresh runs weekly and never "
            f"retrains: it harvests the last seven days by `EDAT`, verifies the DOIs, tags "
            f"the new papers with `debris_v1`, scores novelty, rebuilds the JSON bundles and "
            f"pushes data to the droplet. A re-run over the same week adds nothing.\n")


def next_run() -> str:
    """The next fire time of the launchd plist (path B), read from the plist itself."""
    plist = c.ROOT / "deploy" / "com.mdeller.debris.weekly.plist"
    if not plist.exists():
        return "no timer definition found"
    with plist.open("rb") as fh:
        spec = plistlib.load(fh).get("StartCalendarInterval", {})
    weekday, hour, minute = (spec.get("Weekday", 0), spec.get("Hour", 2),
                             spec.get("Minute", 0))
    today = date.today()
    # launchd counts Sunday as 0; date.weekday() counts Monday as 0.
    ahead = (weekday - (today.weekday() + 1) % 7) % 7
    when = datetime.combine(today + timedelta(days=ahead or 7),
                            datetime.min.time()).replace(hour=hour, minute=minute)
    names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    return f"{names[weekday]} {when:%Y-%m-%d} at {when:%H:%M} local, `{plist.name}`"


# ------------------------------------------------------------------------ writer

def build() -> str:
    conn = c.connect(readonly=True)
    try:
        parts = [
            "# DEBRIS findings\n",
            f"Generated from `data/debris.sqlite` on "
            f"{c.now()[:16].replace('T', ' ')} UTC. "
            "Regenerate with `pixi run findings`.\n",
            "DEBRIS indexes what the literature reports. A tag records a polymer detected, "
            "an association observed or a mechanism shown; nothing here asserts that plastics "
            "cause disease in people. The evidence rungs are ordered so a reader can see how "
            "far from a human outcome each claim sits.\n",
            corpus_section(conn),
            funnel_section(conn),
            tagger_section(),
            organ_section(conn),
            pathway_section(conn),
            gold_section(conn),
            vocabulary_section(conn),
            gaps_section(conn),
            operations_section(conn),
        ]
    finally:
        conn.close()
    return "\n".join(parts)


def main() -> int:
    target = c.ROOT / "FINDINGS.md"
    appended = ""
    if target.exists():
        existing = target.read_text()
        if (idx := existing.find(DRIFT_MARKER)) != -1:
            appended = "\n" + existing[idx:].rstrip() + "\n"
    target.write_text(build() + appended)
    words = len(re.findall(r"\S+", target.read_text()))
    c.log(f"findings: wrote FINDINGS.md, {words} words"
          + (", drift recommendations preserved" if appended else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
