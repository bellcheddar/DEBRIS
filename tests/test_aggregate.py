"""Aggregate totals must reconcile with SQL, and the Venn must not double count."""
from __future__ import annotations

from pipeline import aggregate
from pipeline import common as c

# These queries are written out by hand rather than imported, so a mistake in the aggregate
# cannot hide behind the same mistake in the test. The one rule stated once is the corpus
# rule: a paper harvested only as a negative control is not corpus, whatever its tag says.
NOT_CONTROL = "COALESCE(p.hit_strategy,'') <> 'negative'"


def test_meta_matches_sql(corpus):
    conn = c.connect(corpus)
    meta = aggregate.meta_bundle(conn)
    assert meta["verified_papers"] == conn.execute(
        f"""SELECT COUNT(*) FROM papers p WHERE doi_status='verified'
              AND {NOT_CONTROL}""").fetchone()[0]
    assert meta["relevant_papers"] == conn.execute(
        f"""SELECT COUNT(*) FROM tags t JOIN papers p USING (pmid)
           WHERE p.doi_status='verified' AND t.relevant=1 AND {NOT_CONTROL}""").fetchone()[0]
    assert meta["pet_papers"] == conn.execute(
        f"""SELECT COUNT(*) FROM tags t JOIN papers p USING (pmid)
           WHERE p.doi_status='verified' AND t.relevant=1 AND {NOT_CONTROL} AND t.pet_specific=1
             AND {NOT_CONTROL}""").fetchone()[0]
    assert meta["review_queue"] == 1


def test_polymer_rows_match_sql(corpus):
    conn = c.connect(corpus)
    cell = aggregate.atlas_bundle(conn)["cells"]["all"]["all"]
    for row in cell["polymers"]:
        expected = conn.execute(
            f"""SELECT COUNT(DISTINCT p.pmid) FROM papers p JOIN tags t USING (pmid)
                JOIN tag_polymers pl ON pl.pmid=p.pmid
                WHERE p.doi_status='verified' AND t.relevant=1 AND {NOT_CONTROL}
                  AND pl.polymer = ?""", (row["k"],)).fetchone()[0]
        assert row["n"] == expected, row["k"]


def test_a_two_polymer_paper_makes_a_pair_and_one_exact_combination(corpus):
    """1002 carries PET and PS: one pair, and one combination that is exactly those two."""
    conn = c.connect(corpus)
    cell = aggregate.atlas_bundle(conn)["cells"]["all"]["all"]
    pair = next(p for p in cell["pairs"] if {p["a"], p["b"]} == {"PET", "PS"})
    assert pair["n"] == 1
    assert {"k": ["PET", "PS"], "n": 1} in cell["combos"]
    # and PET alone is its own combination, not folded into the pair
    assert {"k": ["PET"], "n": 1} in cell["combos"]


def test_every_paper_lands_in_exactly_one_combination(corpus):
    """The combinations partition the corpus, which is the one thing a Venn region does."""
    conn = c.connect(corpus)
    cell = aggregate.atlas_bundle(conn)["cells"]["all"]["all"]
    tagged = conn.execute(
        f"""SELECT COUNT(DISTINCT p.pmid) FROM papers p JOIN tags t USING (pmid)
            JOIN tag_polymers pl ON pl.pmid=p.pmid
            WHERE p.doi_status='verified' AND t.relevant=1 AND {NOT_CONTROL}""").fetchone()[0]
    assert sum(cmb["n"] for cmb in cell["combos"]) == tagged


def test_organ_chip_narrows_the_corpus(corpus):
    conn = c.connect(corpus)
    cells = aggregate.atlas_bundle(conn)["cells"]
    assert cells["heart"]["all"]["verified"] < cells["all"]["all"]["verified"]
    assert cells["heart"]["all"]["verified"] == conn.execute(
        f"""SELECT COUNT(DISTINCT p.pmid) FROM papers p JOIN tags t USING (pmid)
           JOIN tag_organs o ON o.pmid=p.pmid
           WHERE p.doi_status='verified' AND t.relevant=1 AND {NOT_CONTROL}
             AND o.organ_system='cardiovascular'""").fetchone()[0]


def test_ladder_rows_do_not_double_count_a_paper_within_a_rung(corpus):
    conn = c.connect(corpus)
    rows = aggregate.ladder_rows(conn, pet_only=False)
    for row in rows:
        for rung_index, count in enumerate(row["rungs"], 1):
            expected = conn.execute(
                f"""SELECT COUNT(DISTINCT p.pmid) FROM papers p JOIN tags t USING (pmid)
                   JOIN tag_diseases d ON d.pmid=p.pmid JOIN tag_rungs r ON r.pmid=p.pmid
                   WHERE p.doi_status='verified' AND t.relevant=1 AND {NOT_CONTROL}
                     AND d.disease_category=? AND r.rung=?""",
                (row["key"], rung_index)).fetchone()[0]
            assert count == expected


def test_ladder_always_has_six_rungs(corpus):
    conn = c.connect(corpus)
    for row in aggregate.ladder_rows(conn, pet_only=False):
        assert len(row["rungs"]) == 6


def test_pet_scope_is_a_subset(corpus):
    conn = c.connect(corpus)
    all_rows = {r["key"]: r for r in aggregate.ladder_rows(conn, False)}
    for row in aggregate.ladder_rows(conn, True):
        for i, count in enumerate(row["rungs"]):
            assert count <= all_rows[row["key"]]["rungs"][i]


def test_body_counts_match_sql(corpus):
    conn = c.connect(corpus)
    for node in aggregate.body_bundle(conn)["nodes"]:
        values = node["tissues"] or node["organs"]
        table, column = ("tag_tissues", "tissue") if node["tissues"] else ("tag_organs", "organ_system")
        marks = ",".join("?" * len(values))
        expected = conn.execute(
            f"""SELECT COUNT(DISTINCT p.pmid) FROM papers p JOIN tags t USING (pmid)
                JOIN {table} o ON o.pmid=p.pmid
                WHERE p.doi_status='verified' AND t.relevant=1 AND {NOT_CONTROL}
                  AND o.{column} IN ({marks})""", values).fetchone()[0]
        assert node["count"] == expected
        assert node["pet_count"] <= node["count"]


def test_sankey_links_reference_real_nodes(corpus):
    conn = c.connect(corpus)
    sankey = aggregate.pathways_bundle(conn)["sankey"]
    assert len(sankey["labels"]) == len(sankey["keys"]) == len(sankey["kinds"])
    for link in sankey["links"]:
        assert 0 <= link["source"] < len(sankey["labels"])
        assert 0 <= link["target"] < len(sankey["labels"])
        assert link["value"] > 0


def test_unverified_and_irrelevant_papers_are_excluded(corpus):
    conn = c.connect(corpus)
    bundle = aggregate.atlas_bundle(conn)
    # 1006 is unresolved, 1007 is irrelevant: neither may reach a chart.
    assert bundle["cells"]["all"]["all"]["verified"] == conn.execute(
        f"""SELECT COUNT(*) FROM papers p LEFT JOIN tags t USING (pmid)
           WHERE p.doi_status='verified' AND (t.relevant IS NULL OR t.relevant=1)
             AND {NOT_CONTROL}""").fetchone()[0]


def test_the_year_trend_ends_today_with_no_future_dates():
    import datetime as dt
    from pipeline import aggregate

    rows = [{"day": "2024-03-01", "pet": 0}, {"day": "2025-06-15", "pet": 1},
            {"day": "2025-10-01", "pet": 0}, {"day": "2027-01-01", "pet": 0}]
    trend = aggregate.trailing_year(rows, today=dt.date(2025, 10, 30))
    assert trend[-1] == {"date": "2025-10-30", "n": 2, "pet_n": 1, "by": {}}
    assert all(r["date"] <= "2025-10-30" for r in trend)
    assert trend[0]["date"] == "2025-02-28"


def test_the_year_trend_counts_each_polymer():
    import datetime as dt
    from pipeline import aggregate

    rows = [{"day": "2025-06-15", "pet": 1, "polymers": ["PET", "PS"]},
            {"day": "2025-10-01", "pet": 0, "polymers": ["PS"]}]
    trend = aggregate.trailing_year(rows, today=dt.date(2026, 3, 1))
    assert trend[-1]["by"] == {"PET": 1, "PS": 2}


def test_gap_map_counts_papers_with_evidence_in_people(corpus):
    """1002 names PET and PS with pulmonary fibrosis at rungs 1 and 4: both cells hold one
    paper with evidence in people; the negative controls never reach the map."""
    conn = c.connect()
    gap = aggregate.polymers_bundle(conn, [])["gap"]
    cells = {(x["p"], x["d"]): x for x in gap["cells"]}
    assert cells[("PET", "pulmonary_fibrosis")]["n"] == 1
    assert cells[("PET", "pulmonary_fibrosis")]["human"] == 1
    assert cells[("PS", "neuroinflammation_neurodegeneration")]["human"] == 0
    assert cells[("PS", "neuroinflammation_neurodegeneration")]["best"] == 2   # animals
    assert sum(x["n"] for x in gap["cells"]) == 7   # 1001, 1002 twice, 1003, 1004 twice, 1005


def test_pet_watch_counts_papers_naming_pet(corpus):
    """1001 and 1002 name PET (the fixture default and an explicit pair); the controls and
    the irrelevant paper never count."""
    pet = aggregate.pet_bundle(c.connect())
    assert pet["total"] == 2
    assert pet["rungs"] == {"1": 2, "2": 1, "4": 1}
    assert {r["key"] for r in pet["pathways"]} == {"oxidative_stress"}
