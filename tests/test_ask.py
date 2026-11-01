"""DEBRIS LLM (D69): the counted leads, the checks on model readings, and the bundle."""
from __future__ import annotations

from pipeline import ask
from pipeline import common as c

PET = ask.PLASTICS[4]
CARDIO = ask.PLACES[3]


def test_lead_carries_the_count_and_never_a_cause():
    assert ask.lead(PET, CARDIO, 1, 1) == "1 paper on the heart and blood vessels detects PET in people."
    assert ask.lead(PET, CARDIO, 2, 1234).startswith("1,234 papers")
    for q in ask.QUESTIONS:
        for n in (0, 1, 7):
            assert not ask.CAUSAL.search(ask.lead(PET, CARDIO, q["r"], n))


def test_check_drops_causal_wording_stray_figures_and_house_style():
    src = "Question: PET. Summary: 12 of 13 lung samples held microplastics (2022)."
    assert ask.check("Microplastics were found in 12 of 13 lung samples.", src)[0]
    assert ask.check("PET causes heart disease in people.", src) == (None, "causal wording")
    assert ask.check("This leads to stroke.", src)[1] == "causal wording"
    assert ask.check("Found in 40 samples.", src)[1].startswith("figures not in the input")
    assert ask.check("A seamless finding.", src)[1] == "house style"
    assert ask.check("", src) == (None, "empty")
    # In animals or cells a causal verb may stand, but never beside people.
    assert ask.check("PS caused liver damage in mice.", src, 3)[0]
    assert ask.check("PS caused liver damage in mice and in people.", src, 3)[1] == "causal wording"
    assert ask.check("PS caused liver damage in mice.", src, 1)[1] == "causal wording"
    assert ask.check("PS caused liver damage.", src, 4)[1] == "causal wording"
    # An effect in people stands only as an association; human cells are a lab model.
    assert ask.check("PET impaired erectile function in human tissue and rats.", src, 4)[1] == "effect in people"
    assert ask.check("PS reduced sperm function in humans.", src, 4)[1] == "effect in people"
    assert ask.check("Levels were associated with reduced ovarian reserve in women.", src)[0]
    assert ask.check("In human brain organoids, PS induced DNA damage.", src, 4)[0]
    assert ask.check("Low-dose PS reduced sperm motility in adult male rats.", src, 5)[0]
    assert ask.check("A human-relevant mixture promoted tumours in the mouse colon.", src, 5)[0]


def test_bundle_shows_a_reading_only_for_the_papers_it_was_written_from(corpus):
    conn = c.connect()
    c.migrate(conn)
    b = ask.bundle(conn)
    assert len(b["answers"]) == len(ask.PLASTICS) * len(ask.PLACES) * len(ask.QUESTIONS)
    k = ask.key("PET", "cardiovascular", 1)
    a = b["answers"][k]
    assert a["n"] >= 1 and a["papers"] and a["reading"] is None
    job = next(j for j in ask.jobs(conn) if j["key"] == k)
    with conn:
        conn.execute("INSERT INTO ask_answers VALUES (?,?,?,?,?,?)",
                     (k, job["hash"], "Detected in plaque.", "ok", "m", c.now()))
    assert ask.bundle(conn)["answers"][k]["reading"] == "Detected in plaque."
    with conn:
        conn.execute("UPDATE ask_answers SET input_hash = 'stale' WHERE key = ?", (k,))
    assert ask.bundle(conn)["answers"][k]["reading"] is None
