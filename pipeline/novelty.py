"""Novelty scoring (spec 5.7). No LLM: pure set arithmetic over the tag tables.

For every newly admitted paper, each (polymer, organ_system, pathway) triple and
(polymer, disease_category) pair that the corpus had not seen before sets novel = 1
and writes a novelty_events row. A new maximum rung for a (polymer, disease_category)
writes a ladder_events row.

  pixi run novelty --run <ingest_run>
"""
from __future__ import annotations

import argparse

from pipeline import common as c


def combinations(conn, pmids: set[str] | None = None) -> tuple[set[str], set[str]]:
    """(triples, pairs) present in the corpus, optionally restricted to some papers."""
    clause = ""
    params: list = []
    if pmids is not None:
        if not pmids:
            return set(), set()
        marks = ",".join("?" * len(pmids))
        clause = f" AND p.pmid IN ({marks})"
        params = list(pmids)
    triples = {f"{r[0]}|{r[1]}|{r[2]}" for r in conn.execute(f"""
        SELECT pl.polymer, o.organ_system, pa.pathway
        FROM papers p JOIN tags t USING (pmid)
        JOIN tag_polymers pl ON pl.pmid = p.pmid
        JOIN tag_organs o ON o.pmid = p.pmid
        JOIN tag_pathways pa ON pa.pmid = p.pmid
        WHERE p.doi_status='verified' AND t.relevant=1{clause}""", params)}
    pairs = {f"{r[0]}|{r[1]}" for r in conn.execute(f"""
        SELECT pl.polymer, d.disease_category
        FROM papers p JOIN tags t USING (pmid)
        JOIN tag_polymers pl ON pl.pmid = p.pmid
        JOIN tag_diseases d ON d.pmid = p.pmid
        WHERE p.doi_status='verified' AND t.relevant=1 AND d.disease_category <> 'none'{clause}""",
        params)}
    return triples, pairs


def max_rungs(conn, exclude: set[str] | None = None) -> dict[str, int]:
    """Highest rung per (polymer, disease_category), optionally ignoring some papers."""
    clause = ""
    params: list = []
    if exclude:
        marks = ",".join("?" * len(exclude))
        clause = f" AND p.pmid NOT IN ({marks})"
        params = list(exclude)
    out: dict[str, int] = {}
    for polymer, category, rung in conn.execute(f"""
            SELECT pl.polymer, d.disease_category, MAX(r.rung)
            FROM papers p JOIN tags t USING (pmid)
            JOIN tag_polymers pl ON pl.pmid = p.pmid
            JOIN tag_diseases d ON d.pmid = p.pmid
            JOIN tag_rungs r ON r.pmid = p.pmid
            WHERE p.doi_status='verified' AND t.relevant=1
              AND d.disease_category <> 'none'{clause}
            GROUP BY pl.polymer, d.disease_category""", params):
        out[f"{polymer}|{category}"] = rung
    return out


def paper_combinations(conn, pmid: str) -> tuple[set[str], set[str], dict[str, int]]:
    triples, pairs = combinations(conn, {pmid})
    rungs = max_rungs(conn, exclude=None)
    own = {}
    for polymer, category, rung in conn.execute("""
            SELECT pl.polymer, d.disease_category, MAX(r.rung)
            FROM tag_polymers pl JOIN tag_diseases d ON d.pmid = pl.pmid
            JOIN tag_rungs r ON r.pmid = pl.pmid
            WHERE pl.pmid = ? AND d.disease_category <> 'none'
            GROUP BY pl.polymer, d.disease_category""", (pmid,)):
        own[f"{polymer}|{category}"] = rung
    return triples, pairs, own


def main() -> None:
    ap = argparse.ArgumentParser(description="Score novelty for one ingest run")
    ap.add_argument("--run", required=True, help="ingest run to score")
    ap.add_argument("--reset", action="store_true",
                    help="clear this run's events first (makes a re-run idempotent)")
    args = ap.parse_args()

    conn = c.connect()
    new_pmids = [r[0] for r in conn.execute(
        """SELECT p.pmid FROM papers p JOIN tags t USING (pmid)
           WHERE p.ingest_run = ? AND p.doi_status='verified' AND t.relevant=1""",
        (args.run,))]
    if not new_pmids:
        c.log(f"novelty: no newly admitted relevant papers in {args.run}")
        return

    with conn:
        if args.reset:
            conn.execute("DELETE FROM novelty_events WHERE ingest_run=?", (args.run,))
            conn.execute("DELETE FROM ladder_events WHERE ingest_run=?", (args.run,))

    # The baseline is the corpus without this run's papers, so a re-run of the same
    # ingest reproduces the same events rather than finding nothing.
    others = set(r[0] for r in conn.execute(
        "SELECT pmid FROM papers WHERE ingest_run <> ? OR ingest_run IS NULL", (args.run,)))
    base_triples, base_pairs = combinations(conn, others)
    base_rungs = max_rungs(conn, exclude=set(new_pmids))

    events: list[tuple] = []
    ladder: list[tuple] = []
    novel_papers: set[str] = set()
    seen_triples, seen_pairs = set(base_triples), set(base_pairs)
    running_rungs = dict(base_rungs)

    for pmid in new_pmids:
        triples, pairs, own_rungs = paper_combinations(conn, pmid)
        for triple in sorted(triples - seen_triples):
            events.append((pmid, "triple", triple, args.run))
            novel_papers.add(pmid)
        for pair in sorted(pairs - seen_pairs):
            events.append((pmid, "pair", pair, args.run))
            novel_papers.add(pmid)
        seen_triples |= triples
        seen_pairs |= pairs
        for key, rung in own_rungs.items():
            if rung > running_rungs.get(key, 0):
                polymer, category = key.split("|", 1)
                ladder.append((pmid, polymer, category, rung, args.run))
                running_rungs[key] = rung

    with conn:
        conn.executemany("""INSERT INTO novelty_events (pmid,kind,key,ingest_run)
                            VALUES (?,?,?,?)""", events)
        conn.executemany("""INSERT INTO ladder_events (pmid,polymer,disease_category,
                              new_max_rung,ingest_run) VALUES (?,?,?,?,?)""", ladder)
        conn.execute("UPDATE ingest_runs SET novel=? WHERE run_id=?",
                     (len(novel_papers), args.run))
    c.log(f"novelty: {args.run}: {len(novel_papers)} papers with a new combination, "
          f"{len(events)} events ({sum(1 for e in events if e[1] == 'triple')} triples), "
          f"{len(ladder)} new maximum rungs")


if __name__ == "__main__":
    main()
