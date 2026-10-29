"""Aggregate totals must reconcile with SQL, and the Venn must not double count."""
from __future__ import annotations

from pipeline import aggregate
from pipeline import common as c


def test_meta_matches_sql(corpus):
    conn = c.connect(corpus)
    meta = aggregate.meta_bundle(conn)
    assert meta["verified_papers"] == conn.execute(
        "SELECT COUNT(*) FROM papers WHERE doi_status='verified'").fetchone()[0]
    assert meta["relevant_papers"] == conn.execute(
        """SELECT COUNT(*) FROM tags t JOIN papers p USING (pmid)
           WHERE p.doi_status='verified' AND t.relevant=1""").fetchone()[0]
    assert meta["pet_papers"] == conn.execute(
        """SELECT COUNT(*) FROM tags t JOIN papers p USING (pmid)
           WHERE p.doi_status='verified' AND t.relevant=1 AND t.pet_specific=1""").fetchone()[0]
    assert meta["review_queue"] == 1


def test_venn_regions_sum_to_papers_with_those_polymers(corpus):
    conn = c.connect(corpus)
    bundle = aggregate.atlas_bundle(conn)
    cell = bundle["cells"]["all"]["all"]
    regions = cell["venn_main"]
    main_members = {m for _, members in aggregate.MAIN_SETS for m in members}
    marks = ",".join("?" * len(main_members))
    expected = conn.execute(
        f"""SELECT COUNT(DISTINCT p.pmid) FROM papers p JOIN tags t USING (pmid)
            JOIN tag_polymers pl ON pl.pmid=p.pmid
            WHERE p.doi_status='verified' AND t.relevant=1
              AND pl.polymer IN ({marks})""", list(main_members)).fetchone()[0]
    assert sum(regions.values()) == expected, "a paper is counted in exactly one region"


def test_venn_puts_a_two_polymer_paper_in_the_overlap(corpus):
    conn = c.connect(corpus)
    regions = aggregate.atlas_bundle(conn)["cells"]["all"]["all"]["venn_main"]
    # 1002 carries PET and PS, so it must land in '110' and nowhere else.
    assert regions.get("110", 0) == 1
    assert regions.get("100", 0) == 1  # 1001, PET only


def test_organ_chip_narrows_the_corpus(corpus):
    conn = c.connect(corpus)
    cells = aggregate.atlas_bundle(conn)["cells"]
    assert cells["heart"]["all"]["verified"] < cells["all"]["all"]["verified"]
    assert cells["heart"]["all"]["verified"] == conn.execute(
        """SELECT COUNT(DISTINCT p.pmid) FROM papers p JOIN tags t USING (pmid)
           JOIN tag_organs o ON o.pmid=p.pmid
           WHERE p.doi_status='verified' AND t.relevant=1
             AND o.organ_system='cardiovascular'""").fetchone()[0]


def test_ladder_rows_do_not_double_count_a_paper_within_a_rung(corpus):
    conn = c.connect(corpus)
    rows = aggregate.ladder_rows(conn, pet_only=False)
    for row in rows:
        for rung_index, count in enumerate(row["rungs"], 1):
            expected = conn.execute(
                """SELECT COUNT(DISTINCT p.pmid) FROM papers p JOIN tags t USING (pmid)
                   JOIN tag_diseases d ON d.pmid=p.pmid JOIN tag_rungs r ON r.pmid=p.pmid
                   WHERE p.doi_status='verified' AND t.relevant=1
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
        marks = ",".join("?" * len(node["organs"]))
        expected = conn.execute(
            f"""SELECT COUNT(DISTINCT p.pmid) FROM papers p JOIN tags t USING (pmid)
                JOIN tag_organs o ON o.pmid=p.pmid
                WHERE p.doi_status='verified' AND t.relevant=1
                  AND o.organ_system IN ({marks})""", node["organs"]).fetchone()[0]
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
        """SELECT COUNT(*) FROM papers p LEFT JOIN tags t USING (pmid)
           WHERE p.doi_status='verified' AND (t.relevant IS NULL OR t.relevant=1)""").fetchone()[0]
