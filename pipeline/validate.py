"""Corpus validation and the positive controls (spec section 9).

Asserts the gold papers carry the tags they must, checks the negatives are rejected
and reports the verification funnel. A failure after the training fallback ladder
opens G2 only if it would change a headline Atlas figure; otherwise it is logged
degraded and the build continues (spec 0.2).

  pixi run validate
"""
from __future__ import annotations

import argparse
import json

from pipeline import common as c

# Expectations per gold key (spec section 9). A missing paper is reported, not fatal.
CONTROLS = {
    # The spec (section 9) expects PET and PVC here. Marfella et al. (NEJM 2024)
    # actually report polyethylene and, in a smaller proportion, polyvinyl chloride:
    # no PET. The control follows the paper, not the spec, and pet_specific is
    # therefore not asserted. Logged in DECISIONS.md.
    "carotid_plaque_cohort": {"polymers_superset": {"PE", "PVC"}, "organs": {"cardiovascular"},
                              "model_type": {"human_tissue", "human_cohort"},
                              "rungs_superset": {1, 2}, "headline": True},
    "blood_detection": {"organs": {"hematologic"}, "rungs_superset": {1}, "headline": True},
    "lung_tissue": {"organs": {"respiratory"}, "rungs_superset": {1}, "headline": True},
    "brain_accumulation": {"organs": {"neurological"}, "rungs_superset": {1}, "headline": True},
    "placenta_detection": {"organs": {"reproductive_placental"}, "rungs_superset": {1},
                           "headline": False},
    "broad_review": {"model_type": {"review", "meta_analysis"}, "rungs_empty": True,
                     "headline": False},
}


def tag_of(conn, pmid: str) -> dict | None:
    row = conn.execute("SELECT tag_json FROM tags WHERE pmid=?", (pmid,)).fetchone()
    return json.loads(row[0]) if row and row[0] else None


def check_controls(conn) -> tuple[list[dict], list[str]]:
    results, headline_failures = [], []
    gold = conn.execute("SELECT key, pmid, expect FROM gold_set WHERE pmid <> ''").fetchall()
    for row in gold:
        expect = CONTROLS.get(row["key"])
        tag = tag_of(conn, row["pmid"])
        title = conn.execute("SELECT title, doi_status FROM papers WHERE pmid=?",
                             (row["pmid"],)).fetchone()
        entry = {"key": row["key"], "pmid": row["pmid"], "expect": row["expect"],
                 "title": (title["title"] if title else "")[:120],
                 "doi_status": title["doi_status"] if title else "absent",
                 "problems": [], "tag": tag}
        if expect is None:
            results.append(entry)
            continue
        if tag is None:
            entry["problems"].append("not tagged")
        else:
            if sup := expect.get("polymers_superset"):
                if not sup <= set(tag["polymers"]):
                    entry["problems"].append(
                        f"polymers {sorted(tag['polymers'])} missing {sorted(sup - set(tag['polymers']))}")
            if organs := expect.get("organs"):
                if not organs & set(tag["organ_systems"]):
                    entry["problems"].append(f"organ systems {sorted(tag['organ_systems'])}")
            if models := expect.get("model_type"):
                if tag["model_type"] not in models:
                    entry["problems"].append(f"model_type {tag['model_type']}")
            if rungs := expect.get("rungs_superset"):
                if not rungs <= set(tag["evidence_rungs"]):
                    entry["problems"].append(f"rungs {tag['evidence_rungs']}")
            if expect.get("rungs_empty") and tag["evidence_rungs"]:
                entry["problems"].append(f"a review carries rungs {tag['evidence_rungs']}")
            if expect.get("pet_specific") and not tag["pet_specific"]:
                entry["problems"].append("pet_specific is false")
        if entry["problems"] and expect.get("headline"):
            headline_failures.append(f"{row['key']}: {'; '.join(entry['problems'])}")
        results.append(entry)
    return results, headline_failures


def check_negatives(conn) -> dict:
    """The harvested negatives must be tagged relevant = 0."""
    rows = conn.execute("""SELECT p.pmid, p.title, t.relevant FROM papers p
                           JOIN tags t USING (pmid)
                           WHERE p.hit_strategy LIKE '%negative%'""").fetchall()
    wrong = [dict(r) for r in rows if r["relevant"]]
    return {"n": len(rows), "misclassified": len(wrong),
            "rate": round(len(wrong) / len(rows), 4) if rows else None,
            "examples": wrong[:10]}


def funnel(conn) -> dict:
    statuses = dict(conn.execute("SELECT doi_status, COUNT(*) FROM papers GROUP BY doi_status"))
    strategies = dict(conn.execute("SELECT hit_strategy, COUNT(*) FROM papers GROUP BY hit_strategy"))
    return {"doi_status": statuses, "hit_strategy": strategies,
            "retracted": conn.execute("SELECT COUNT(*) FROM papers WHERE retracted=1").fetchone()[0],
            "no_abstract": conn.execute(
                "SELECT COUNT(*) FROM papers WHERE abstract=''").fetchone()[0],
            "tagged": conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0],
            "relevant": conn.execute("SELECT COUNT(*) FROM tags WHERE relevant=1").fetchone()[0],
            "queued": conn.execute(
                "SELECT COUNT(*) FROM review_queue WHERE resolved_at IS NULL").fetchone()[0]}


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate the corpus and the positive controls")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args()
    conn = c.connect()
    controls, headline = check_controls(conn)
    report = {"funnel": funnel(conn), "controls": controls, "negatives": check_negatives(conn),
              "headline_failures": headline}
    (c.ROOT / "data" / "validation.json").write_text(json.dumps(report, indent=1))
    if args.json:
        print(json.dumps(report, indent=1))
    passed = sum(1 for e in controls if not e["problems"])
    c.log(f"validate: gold controls {passed}/{len(controls)} clean, "
          f"negatives misclassified {report['negatives']['misclassified']}/"
          f"{report['negatives']['n']}, headline failures {len(headline)}")
    if headline:
        c.log("validate: headline control failures: " + " | ".join(headline))


if __name__ == "__main__":
    main()
