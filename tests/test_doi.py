"""DOI verification logic, with Crossref mocked: no network in the test suite."""
from __future__ import annotations

import json
import types

import pytest

from pipeline import verify_doi


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


def crossref(title, status=200, extra=None):
    message = {"title": [title], "type": "journal-article"}
    message.update(extra or {})
    return FakeResponse(status, {"message": message})


@pytest.fixture
def no_limit():
    return verify_doi.c.RateLimiter(1000)


def patch_get(monkeypatch, response):
    monkeypatch.setattr(verify_doi.c, "http_get", lambda *a, **k: response)


def test_matching_title_is_verified(monkeypatch, no_limit):
    patch_get(monkeypatch, crossref("Microplastics in human carotid plaque"))
    pmid, status, retracted, note = verify_doi.check(
        "1", "10.1/x", "Microplastics in Human Carotid Plaque.", no_limit)
    assert status == "verified" and retracted == 0 and "100" in note


def test_title_mismatch_is_rejected(monkeypatch, no_limit):
    patch_get(monkeypatch, crossref("An entirely different paper about marine sediment"))
    _, status, _, _ = verify_doi.check("1", "10.1/x", "Microplastics in carotid plaque", no_limit)
    assert status == "title_mismatch"


def test_missing_doi_needs_no_request(monkeypatch, no_limit):
    def explode(*a, **k):
        raise AssertionError("Crossref must not be called without a DOI")
    monkeypatch.setattr(verify_doi.c, "http_get", explode)
    _, status, _, note = verify_doi.check("1", None, "A title", no_limit)
    assert status == "missing" and "no DOI" in note


def test_404_is_unresolved(monkeypatch, no_limit):
    patch_get(monkeypatch, FakeResponse(404))
    _, status, _, _ = verify_doi.check("1", "10.1/x", "A title", no_limit)
    assert status == "unresolved"


def test_network_error_is_unresolved_not_fatal(monkeypatch, no_limit):
    def boom(*a, **k):
        raise verify_doi.c.TransientHTTP("502")
    monkeypatch.setattr(verify_doi.c, "http_get", boom)
    _, status, _, note = verify_doi.check("1", "10.1/x", "A title", no_limit)
    assert status == "unresolved" and "crossref error" in note


def test_retraction_is_flagged_but_still_verified(monkeypatch, no_limit):
    patch_get(monkeypatch, crossref("A retracted study of nanoplastics",
                                    extra={"update-to": [{"type": "retraction"}]}))
    _, status, retracted, _ = verify_doi.check(
        "1", "10.1/x", "A retracted study of nanoplastics", no_limit)
    assert status == "verified" and retracted == 1


def test_title_normalisation_strips_markup_brackets_and_case():
    assert verify_doi.normalise("<i>In vivo</i> uptake.") == "in vivo uptake"
    assert verify_doi.normalise("[A Translated Title]") == "a translated title"


def test_case_difference_alone_still_verifies(monkeypatch, no_limit):
    patch_get(monkeypatch, crossref("microplastics in human carotid plaque"))
    _, status, _, note = verify_doi.check(
        "1", "10.1/x", "Microplastics in Human Carotid Plaque.", no_limit)
    assert status == "verified" and note.endswith("100.0")


def test_match_floor_is_ninety():
    # Documented in the spec (5.2); a drift here silently changes the corpus.
    assert verify_doi.MATCH_FLOOR == 90
