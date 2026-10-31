"""Shared fixtures: a tiny synthetic corpus in a temporary SQLite database."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import common as c  # noqa: E402


def insert_paper(conn, pmid, *, title="A title", doi_status="verified", year=2024,
                 journal="J Test", relevant=1, polymers=("PET",), organs=("cardiovascular",),
                 diseases=(("atherosclerosis_mace", "carotid artery disease"),),
                 pathways=("oxidative_stress",), rungs=(1, 2), pet=1, run="run-test",
                 abstract="An abstract long enough to be tagged.", model_type="human_tissue",
                 strategy="mesh"):
    conn.execute("""INSERT INTO papers (pmid,doi,doi_status,retracted,title,abstract,journal,year,
                      month,authors,mesh,pub_types,edat,hit_strategy,ingested_at,ingest_run,status)
                    VALUES (?,?,?,0,?,?,?,?,1,'Author A','Microplastics','Journal Article',
                      '2024-01-01',?,?,?,'tagged')""",
                 (pmid, f"10.1000/{pmid}", doi_status, title, abstract, journal, year,
                  strategy, c.now(), run))
    if relevant is not None:
        tag = {"relevant": bool(relevant), "polymers": list(polymers), "size_class": "micro",
               "organ_systems": list(organs), "disease_categories": [d[0] for d in diseases],
               "disease_terms": [d[1] for d in diseases], "pathways": list(pathways),
               "model_type": model_type, "evidence_rungs": list(rungs),
               "pet_specific": bool(pet), "summary": "Detected and associated.",
               "confidence": 0.9}
        conn.execute("""INSERT INTO tags (pmid,relevant,size_class,model_type,pet_specific,summary,
                          confidence,self_consistency,tag_source,tag_json,tagged_at,model_version)
                        VALUES (?,?,?,?,?,?,?,?,'debris_v1',?,?,'debris_v1')""",
                     (pmid, relevant, "micro", model_type, pet, "Detected and associated.",
                      0.9, 0.95, json.dumps(tag), c.now()))
        conn.executemany("INSERT INTO tag_polymers VALUES (?,?)", [(pmid, p) for p in polymers])
        conn.executemany("INSERT INTO tag_organs VALUES (?,?)", [(pmid, o) for o in organs])
        conn.executemany("INSERT INTO tag_diseases VALUES (?,?,?)",
                         [(pmid, d[0], d[1]) for d in diseases])
        conn.executemany("INSERT INTO tag_pathways VALUES (?,?)", [(pmid, p) for p in pathways])
        conn.executemany("INSERT INTO tag_rungs VALUES (?,?)", [(pmid, r) for r in rungs])


@pytest.fixture(autouse=True)
def quiet_build_log(tmp_path, monkeypatch):
    """Keep test runs out of the real BUILD_LOG.md and out of data/manifests/.

    A manifest is how every stage resumes, so a test that writes one into the project
    tells the next real run that work it has never done is already finished.
    """
    monkeypatch.setenv("DEBRIS_LOG", str(tmp_path / "BUILD_LOG.md"))
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    monkeypatch.setattr(c, "MANIFESTS", manifests)


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    """Ten papers: one unverified, one irrelevant, one untagged and two negative
    controls, one of them untagged and one wrongly tagged relevant."""
    db = tmp_path / "debris.sqlite"
    c.init_db(db)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    with conn:
        conn.execute("INSERT INTO ingest_runs (run_id,started_at,harvested) VALUES ('run-test',?,7)",
                     (c.now(),))
        insert_paper(conn, "1001")
        insert_paper(conn, "1002", polymers=("PET", "PS"), organs=("respiratory",),
                     diseases=(("pulmonary_fibrosis", "lung fibrosis"),), rungs=(1, 4))
        insert_paper(conn, "1003", polymers=("PS",), organs=("neurological",), pet=0,
                     diseases=(("neuroinflammation_neurodegeneration", "neuroinflammation"),),
                     rungs=(3, 4, 5), model_type="animal_in_vivo")
        insert_paper(conn, "1004", polymers=("PE", "PP"), organs=("gastrointestinal",), pet=0,
                     diseases=(("ibd_gut", "colitis"),), rungs=(4,), model_type="cell_line")
        insert_paper(conn, "1005", polymers=("PVC",), organs=("hematologic",), pet=0,
                     diseases=(("thrombosis", "venous thrombosis"),), rungs=(1,))
        insert_paper(conn, "1006", doi_status="unresolved")
        insert_paper(conn, "1007", relevant=0, polymers=(), organs=(), diseases=(),
                     pathways=(), rungs=(), pet=0, model_type="not_applicable",
                     title="Positron emission tomography staging")
        insert_paper(conn, "1008", relevant=None)
        insert_paper(conn, "1009", relevant=None, strategy="negative",
                     title="Role of PET/CT in diffuse large B-cell lymphoma")
        insert_paper(conn, "1010", strategy="negative",
                     title="FDG PET/CT in aortitis treatment response")
        conn.execute("INSERT INTO review_queue (pmid,reason,queued_at) VALUES ('1004','low confidence',?)",
                     (c.now(),))
        conn.execute("""INSERT INTO novelty_events (pmid,kind,key,ingest_run)
                        VALUES ('1005','triple','PVC|hematologic|oxidative_stress','last-7-days')""")
    conn.close()
    monkeypatch.setattr(c, "DB_PATH", db)
    return db


@pytest.fixture
def client(corpus, tmp_path, monkeypatch):
    """A Flask test client pointed at the synthetic corpus and its aggregates."""
    monkeypatch.setenv("DEBRIS_DB", str(corpus))
    static_data = tmp_path / "static_data"
    static_data.mkdir()
    monkeypatch.setattr(c, "STATIC_DATA", static_data)
    from pipeline import aggregate
    monkeypatch.setattr(c, "DB_PATH", corpus)
    conn = c.connect(corpus)
    for name, payload in (("meta", aggregate.meta_bundle(conn)),
                          ("atlas", aggregate.atlas_bundle(conn)),
                          ("body", aggregate.body_bundle(conn)),
                          ("pathways", aggregate.pathways_bundle(conn)),
                          ("feed", aggregate.feed_bundle(conn))):
        (static_data / f"{name}.json").write_text(json.dumps(payload))
    conn.close()

    import importlib
    from app import app as app_module
    importlib.reload(app_module)
    app_module.DB_PATH = corpus
    app_module.STATIC_DATA = static_data
    app_module.app.config.update(TESTING=True)
    with app_module.app.test_client() as test_client:
        yield test_client
