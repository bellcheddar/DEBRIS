"""Novelty on a synthetic before/after corpus: new combinations only, and idempotent."""
from __future__ import annotations

import sqlite3
import sys

from pipeline import common as c
from pipeline import novelty
from tests.conftest import insert_paper


def run_novelty(db, run_id, reset=False):
    """novelty.main() reads common.DB_PATH, which the corpus fixture has repointed."""
    argv = ["novelty", "--run", run_id] + (["--reset"] if reset else [])
    old = sys.argv
    sys.argv = argv
    try:
        novelty.main()
    finally:
        sys.argv = old


def events(db, run_id):
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT kind, key FROM novelty_events WHERE ingest_run=?",
                        (run_id,)).fetchall()
    ladder = conn.execute("SELECT polymer, disease_category, new_max_rung FROM ladder_events "
                          "WHERE ingest_run=?", (run_id,)).fetchall()
    conn.close()
    return rows, ladder


def test_first_run_marks_every_combination_new(corpus):
    run_novelty(corpus, "run-test", reset=True)
    rows, ladder = events(corpus, "run-test")
    keys = {key for _, key in rows}
    assert "PET|cardiovascular|oxidative_stress" in keys
    assert any(k == "PET|atherosclerosis_mace" for k in keys)
    assert ladder, "the first run must set a maximum rung per polymer and disease"


def test_rerunning_the_same_ingest_is_idempotent(corpus):
    run_novelty(corpus, "run-test", reset=True)
    first, first_ladder = events(corpus, "run-test")
    run_novelty(corpus, "run-test", reset=True)
    second, second_ladder = events(corpus, "run-test")
    assert sorted(first) == sorted(second)
    assert sorted(first_ladder) == sorted(second_ladder)


def test_a_second_run_only_flags_genuinely_new_combinations(corpus):
    run_novelty(corpus, "run-test", reset=True)
    conn = sqlite3.connect(corpus)
    conn.row_factory = sqlite3.Row
    with conn:
        conn.execute("INSERT INTO ingest_runs (run_id,started_at,harvested) VALUES ('run-2',?,2)",
                     (c.now(),))
        # 2001 repeats an existing PET cardiovascular oxidative-stress triple.
        insert_paper(conn, "2001", run="run-2")
        # 2002 brings a polymer and pathway the corpus has never seen together.
        insert_paper(conn, "2002", run="run-2", polymers=("PA",), organs=("renal",),
                     diseases=(("kidney_disease", "acute kidney injury"),),
                     pathways=("mitochondrial_dysfunction",), rungs=(3, 5), pet=0)
    conn.close()
    run_novelty(corpus, "run-2")
    rows, ladder = events(corpus, "run-2")
    keys = {key for _, key in rows}
    assert "PA|renal|mitochondrial_dysfunction" in keys
    assert not any(k.startswith("PET|cardiovascular") for k in keys), \
        "a repeat combination must not be flagged as novel"
    assert ("PA", "kidney_disease", 5) in ladder


def test_a_higher_rung_writes_a_ladder_event(corpus):
    run_novelty(corpus, "run-test", reset=True)
    conn = sqlite3.connect(corpus)
    with conn:
        conn.execute("INSERT INTO ingest_runs (run_id,started_at,harvested) VALUES ('run-3',?,1)",
                     (c.now(),))
        insert_paper(conn, "3001", run="run-3", polymers=("PET",), organs=("cardiovascular",),
                     diseases=(("atherosclerosis_mace", "carotid artery disease"),),
                     rungs=(5, 6))
    conn.close()
    run_novelty(corpus, "run-3")
    _, ladder = events(corpus, "run-3")
    assert ("PET", "atherosclerosis_mace", 6) in ladder
