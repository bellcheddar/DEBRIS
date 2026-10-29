"""Negative controls are harvested on purpose and must never reach the corpus.

The harvest pulls in a set of hard negatives so the tagger can be shown refusing them:
positron emission tomography and CT papers above all, because `PET` means polyethylene
terephthalate in this corpus and something else entirely in a radiology journal. Those
papers verify at Crossref like any other and they are real published work, so nothing
about the paper itself keeps them out. Provenance does, and it has to hold whether the
paper is untagged, tagged irrelevant, or wrongly tagged relevant.
"""
from __future__ import annotations

import sqlite3

from pipeline import aggregate
from pipeline import common as c
from pipeline import validate

CONTROLS = {"1009", "1010"}


def pmids(client, query: str) -> set[str]:
    return {row["pmid"] for row in client.get(f"/api/papers?{query}").get_json()["data"]}


def test_an_untagged_control_is_not_listed(client):
    """The state the live site was in: nothing tagged, so nothing could be filtered on a tag."""
    listed = pmids(client, "size=50")
    assert "1009" not in listed
    assert "1008" in listed, "an ordinary untagged paper still lists"


def test_a_control_the_tagger_called_relevant_is_not_listed(client):
    """Provenance outranks the tag, so one tagger mistake cannot publish a control."""
    assert "1010" not in pmids(client, "size=50")


def test_neither_switch_reveals_a_control(client):
    """`unverified` and `include_irrelevant` widen the corpus; they do not open the controls."""
    assert not CONTROLS & pmids(client, "unverified=1&size=50")
    assert not CONTROLS & pmids(client, "include_irrelevant=1&size=50")
    assert not CONTROLS & pmids(client, "unverified=1&include_irrelevant=1&size=50")


def test_a_control_does_not_match_a_filter_it_would_otherwise_satisfy(client):
    """1010 is tagged PET, cardiovascular and rung 1, so every one of these would catch it."""
    for query in ("polymer=PET", "organ=cardiovascular", "pet=1", "rung=1", "q=PET"):
        assert not CONTROLS & pmids(client, query), query


def test_the_csv_download_excludes_controls(client):
    body = client.get("/download/debris_latest.csv").get_data(as_text=True)
    for pmid in CONTROLS:
        assert pmid not in body


def test_the_counts_separate_the_corpus_from_the_controls(corpus):
    conn = c.connect(corpus)
    meta = aggregate.meta_bundle(conn)
    assert meta["control_papers"] == 2
    assert meta["verified_papers"] == conn.execute(
        """SELECT COUNT(*) FROM papers WHERE doi_status='verified'
           AND COALESCE(hit_strategy,'') <> 'negative'""").fetchone()[0]
    # the funnel still adds up: nothing has been dropped, only reclassified
    assert meta["verified_papers"] + meta["control_papers"] == conn.execute(
        "SELECT COUNT(*) FROM papers WHERE doi_status='verified'").fetchone()[0]
    conn.close()


def test_a_control_the_real_strategies_also_found_stays_in_the_corpus(corpus):
    """`textword,negative` means a search for the science found it too, so it is corpus."""
    conn = sqlite3.connect(corpus)
    with conn:
        conn.execute("""UPDATE papers SET hit_strategy='textword,negative' WHERE pmid='1010'""")
    conn.close()
    conn = c.connect(corpus)
    meta = aggregate.meta_bundle(conn)
    assert meta["control_papers"] == 1
    assert "1010" in {r[0] for r in conn.execute(
        f"SELECT pmid FROM papers p WHERE {c.corpus_clause()}")}
    conn.close()


def test_controls_are_kept_for_the_negative_control_check(corpus):
    """Excluding them from the corpus must not cost us the proof that the tagger refuses them."""
    conn = c.connect(corpus)
    result = validate.check_negatives(conn)
    assert result["n"] == 1, "the tagged control is still measured"
    assert result["misclassified"] == 1, "and its mistake is still reported"
    conn.close()


def test_the_charts_ignore_a_wrongly_tagged_control(corpus):
    conn = c.connect(corpus)
    atlas = aggregate.atlas_bundle(conn)
    pet_papers = conn.execute(
        f"""SELECT COUNT(*) FROM papers p JOIN tags t USING (pmid)
            WHERE {c.corpus_clause()} AND t.relevant=1 AND t.pet_specific=1""").fetchone()[0]
    assert atlas["cells"]["all"]["pet"]["verified"] == pet_papers
    conn.close()
