"""The header indicator must never read green on a corpus that is not.

health_of() is the only thing standing between a real problem and a reassuring dot, so
each failing signal is checked on its own.
"""
from __future__ import annotations

import datetime as dt

import pytest

from app import app as app_module


def meta(**over):
    base = {"verified_papers": 100, "tagged_papers": 100, "pet_papers": 10,
            "review_queue": 0, "drift_f1": 0.96, "provisional_tags": False,
            "last_ingest_date": dt.date.today().isoformat()}
    base.update(over)
    return base


def test_a_complete_fresh_corpus_is_operational():
    assert app_module.health_of(meta())["state"] == "ok"


def test_untagged_papers_read_as_working_not_broken():
    """A corpus mid-ingest is not a fault, and must not be dressed as one."""
    out = app_module.health_of(meta(tagged_papers=40))
    assert out["state"] == "working"
    assert "60 papers still to tag" in out["detail"]


def test_an_empty_corpus_is_not_healthy():
    assert app_module.health_of(meta(verified_papers=0, tagged_papers=0))["state"] == "attention"


def test_a_stale_refresh_is_not_healthy():
    old = (dt.date.today() - dt.timedelta(days=app_module.STALE_DAYS + 1)).isoformat()
    out = app_module.health_of(meta(last_ingest_date=old))
    assert out["state"] == "attention"
    assert "last refresh" in out["detail"]


def test_drift_below_the_floor_is_not_healthy():
    assert app_module.health_of(meta(drift_f1=0.89))["state"] == "attention"


def test_a_swamped_review_queue_is_not_healthy():
    assert app_module.health_of(meta(review_queue=30))["state"] == "attention"


@pytest.mark.parametrize("stamp", [None, "", "not-a-date"])
def test_an_unreadable_ingest_date_does_not_raise(stamp):
    """A missing or malformed stamp means no completed ingest, not a crashed header."""
    assert app_module.health_of(meta(last_ingest_date=stamp))["state"] == "working"


def test_a_problem_outranks_work_in_progress():
    """Mid-ingest and drifting at once must report the problem, not the progress."""
    assert app_module.health_of(meta(tagged_papers=40, drift_f1=0.5))["state"] == "attention"


def test_the_header_renders_the_indicator(client):
    page = client.get("/").get_data(as_text=True)
    assert 'class="pulse"' in page
    assert 'data-state=' in page
    for link in ("eloratherapeutics.com", "marcdeller.com", "github.com/bellcheddar/DEBRIS"):
        assert link in page
    assert "NHLBI" not in page
