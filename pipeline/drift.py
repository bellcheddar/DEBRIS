"""Weekly drift check (spec 5.7). Never retrains.

With an ANTHROPIC_API_KEY, 20 newly tagged papers are re-tagged by the frontier
model and scored field by field into drift_log. Without one, the self-consistency
distribution and the review rate stand in for it, which is what the app footer
shows. A sustained fall writes a recommendation to FINDINGS.md; nothing else.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics

from pipeline import common as c
from pipeline import schema
from pipeline.train import binary_f1, micro_f1

SAMPLE = 20
RELEVANCE_FLOOR = 0.90
REVIEW_RATE_CEILING = 0.25


def sample_papers(conn, run: str | None, n: int) -> list:
    where = "WHERE p.doi_status='verified' AND t.pmid IS NOT NULL"
    params: list = []
    if run:
        where += " AND p.ingest_run = ?"
        params.append(run)
    rows = conn.execute(f"""SELECT p.pmid, p.title, p.abstract, p.journal, p.year, p.mesh,
                                   t.tag_json, t.self_consistency
                            FROM papers p JOIN tags t USING (pmid) {where}""", params).fetchall()
    random.Random(42).shuffle(rows)
    return rows[:n]


def api_retag(papers: list) -> dict[str, dict]:
    """Re-tag the sample with claude-sonnet-4-5; returns pmid -> validated tag."""
    import anthropic

    client = anthropic.Anthropic(api_key=c.api_key("ANTHROPIC_API_KEY"))
    out: dict[str, dict] = {}
    for paper in papers:
        message = client.messages.create(
            model="claude-sonnet-4-5", max_tokens=1200, system=schema.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": schema.LABEL_INSTRUCTIONS + "\n\n" +
                       schema.user_prompt(dict(paper))}])
        text = "".join(b.text for b in message.content if b.type == "text")
        tag, _, _ = schema.validate(schema.extract_json(text))
        if tag:
            out[paper["pmid"]] = tag
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Measure tagger drift")
    ap.add_argument("--run", default=None)
    ap.add_argument("--sample", type=int, default=SAMPLE)
    args = ap.parse_args()

    conn = c.connect()
    papers = sample_papers(conn, args.run, args.sample)
    if not papers:
        c.log("drift: nothing tagged in this run to sample")
        return
    run_id = args.run or "manual"

    review_rate = 0.0
    total_tagged = conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
    if total_tagged:
        queued = conn.execute(
            "SELECT COUNT(*) FROM review_queue WHERE resolved_at IS NULL").fetchone()[0]
        review_rate = queued / total_tagged
    consistency = [p["self_consistency"] for p in papers if p["self_consistency"] is not None]

    rows: list[tuple] = []
    if c.api_key("ANTHROPIC_API_KEY"):
        reference = api_retag(papers)
        fields = {"relevant": [], "polymers": [], "organ_systems": [], "pathways": [],
                  "disease_categories": []}
        for paper in papers:
            if paper["pmid"] not in reference:
                continue
            ours = json.loads(paper["tag_json"])
            theirs = reference[paper["pmid"]]
            fields["relevant"].append((bool(theirs["relevant"]), bool(ours["relevant"])))
            for field in ("polymers", "organ_systems", "pathways", "disease_categories"):
                fields[field].append((set(theirs[field]), set(ours[field])))
        n = len(fields["relevant"])
        if n:
            rows.append((run_id, "relevant",
                         binary_f1([t for t, _ in fields["relevant"]],
                                   [p for _, p in fields["relevant"]]), n))
            for field in ("polymers", "organ_systems", "pathways", "disease_categories"):
                rows.append((run_id, field, micro_f1(fields[field]), n))
        source = "frontier model"
    else:
        # No key: the self-consistency distribution and the review rate stand in.
        rows.append((run_id, "self_consistency_mean",
                     round(statistics.fmean(consistency), 4) if consistency else 0.0,
                     len(consistency)))
        rows.append((run_id, "self_consistency_p10",
                     round(sorted(consistency)[max(0, len(consistency) // 10)], 4)
                     if consistency else 0.0, len(consistency)))
        rows.append((run_id, "review_rate", round(review_rate, 4), total_tagged))
        source = "self-consistency (no ANTHROPIC_API_KEY)"

    with conn:
        conn.execute("DELETE FROM drift_log WHERE run_id=?", (run_id,))
        conn.executemany("INSERT INTO drift_log (run_id,field,f1,n) VALUES (?,?,?,?)", rows)

    summary = {field: round(value, 3) for _, field, value, _ in rows}
    c.log(f"drift: {run_id} by {source}: {summary}, review rate {review_rate:.1%}")

    # Two consecutive weeks below the floor is a recommendation, never a retrain.
    history = conn.execute("""SELECT run_id, f1 FROM drift_log WHERE field='relevant'
                              ORDER BY rowid DESC LIMIT 2""").fetchall()
    rates = conn.execute("""SELECT run_id, f1 FROM drift_log WHERE field='review_rate'
                            ORDER BY rowid DESC LIMIT 2""").fetchall()
    bad_f1 = len(history) == 2 and all(r["f1"] < RELEVANCE_FLOOR for r in history)
    bad_rate = len(rates) == 2 and all(r["f1"] > REVIEW_RATE_CEILING for r in rates)
    if bad_f1 or bad_rate:
        with (c.ROOT / "FINDINGS.md").open("a") as fh:
            fh.write(f"\n## Drift recommendation ({c.now()[:10]})\n\n"
                     f"Relevance F1 has been below {RELEVANCE_FLOOR} "
                     f"or the review rate above {REVIEW_RATE_CEILING:.0%} for two runs "
                     f"({summary}). Consider training debris_v2 with the review-queue "
                     f"papers added to the training set. The weekly pipeline does not "
                     f"retrain on its own.\n")
        c.log("drift: wrote a retraining recommendation to FINDINGS.md")


if __name__ == "__main__":
    main()
