"""Every route answers, and the API filters do what the charts link to."""
from __future__ import annotations

import json


def test_all_pages_200(client):
    for route in ("/", "/body", "/pathways", "/papers", "/about"):
        assert client.get(route).status_code == 200, route


def test_healthz_reports_the_corpus(client):
    payload = client.get("/healthz").get_json()
    assert payload["status"] == "ok"
    assert payload["papers_in_db"] == 10
    assert payload["database"] is True


def test_api_papers_defaults_to_verified_and_relevant(client):
    data = client.get("/api/papers?size=50").get_json()
    pmids = {row["pmid"] for row in data["data"]}
    assert "1006" not in pmids, "unresolved DOI must be hidden by default"
    assert "1007" not in pmids, "an irrelevant paper must be hidden"
    assert "1008" in pmids, "an untagged paper must still list"


def test_unverified_switch_admits_them(client):
    data = client.get("/api/papers?unverified=1&size=50").get_json()
    assert "1006" in {row["pmid"] for row in data["data"]}


def test_polymer_and_organ_filters(client):
    data = client.get("/api/papers?polymer=PVC").get_json()
    assert [row["pmid"] for row in data["data"]] == ["1005"]
    data = client.get("/api/papers?organ=respiratory").get_json()
    assert [row["pmid"] for row in data["data"]] == ["1002"]


def test_venn_region_query_is_exclusive(client):
    """polymers=PET with not_polymers=PS,PE,PP is the PET-only region."""
    data = client.get("/api/papers?polymers=PET&not_polymers=PS,PE,PP").get_json()
    assert [row["pmid"] for row in data["data"]] == ["1001"]
    both = client.get("/api/papers?polymers=PET|PS").get_json()
    assert [row["pmid"] for row in both["data"]] == ["1002"]


def test_rung_and_pet_filters(client):
    assert {r["pmid"] for r in client.get("/api/papers?rung=5").get_json()["data"]} == {"1003"}
    pet = {r["pmid"] for r in client.get("/api/papers?pet=1").get_json()["data"]}
    assert pet == {"1001", "1002"}


def test_review_and_novel_filters(client):
    assert {r["pmid"] for r in client.get("/api/papers?review=1").get_json()["data"]} == {"1004"}
    assert {r["pmid"] for r in client.get("/api/papers?novel=1").get_json()["data"]} == {"1005"}


def test_search_matches_title_and_pmid(client):
    assert {r["pmid"] for r in client.get("/api/papers?q=1003").get_json()["data"]} == {"1003"}
    hits = client.get("/api/papers?q=A title&size=50").get_json()
    assert hits["last_row"] >= 5


def test_pagination_reports_totals(client):
    page = client.get("/api/papers?size=2&page=1").get_json()
    assert len(page["data"]) == 2
    assert page["last_page"] == -(-page["last_row"] // 2)


def test_paper_detail_carries_tags(client):
    paper = client.get("/paper/1002").get_json()
    assert sorted(paper["polymers"]) == ["PET", "PS"]
    assert paper["rungs"] == [1, 4]
    assert paper["tag"]["model_type"] == "human_tissue"
    assert paper["diseases"][0]["category"] == "pulmonary_fibrosis"
    assert client.get("/paper/does-not-exist").status_code == 404


def test_csv_download_honours_filters(client):
    body = client.get("/download/debris_latest.csv?polymer=PVC").get_data(as_text=True)
    lines = [line for line in body.splitlines() if line.strip()]
    assert lines[0].startswith("pmid,doi,doi_status")
    assert len(lines) == 2 and "1005" in lines[1]


def test_pages_name_the_elora_design_system(client):
    html = client.get("/").get_data(as_text=True)
    assert "Elora" in html and "THERAPEUTICS" in html.upper()
    assert "theme.css" in html


def test_no_causal_claim_in_the_copy(client):
    """Spec 0.1: app copy never claims human causation."""
    banned = ("causes", "caused by", "proves", "proven to cause", "leads to disease")
    for route in ("/", "/body", "/pathways", "/papers", "/about"):
        text = client.get(route).get_data(as_text=True).lower()
        for phrase in banned:
            assert phrase not in text, f"{phrase!r} appears on {route}"


def test_no_em_dashes_in_the_copy(client):
    for route in ("/", "/body", "/pathways", "/papers", "/about"):
        assert "—" not in client.get(route).get_data(as_text=True), route


def test_about_lists_verified_references_and_links_the_models(client):
    html = client.get("/about").get_data(as_text=True)
    assert "https://doi.org/10.1016/j.jhazmat.2026.144001" in html      # Liu et al., the tissues
    assert "https://doi.org/10.1038/s41586-022-04599-z" in html         # FAST-PETase
    assert "https://doi.org/10.1126/science.aad6359" in html            # PETase
    assert "huggingface.co/Dellboy/debris-tagger-v1" in html
    assert 'data-tip=' in html


def test_health_counts_only_papers_the_tagger_can_read():
    from app.app import health_of

    today = __import__("datetime").date.today().isoformat()
    meta = {"verified_papers": 100, "taggable_papers": 90, "tagged_papers": 90,
            "review_queue": 5, "last_ingest_date": today}
    assert health_of(meta)["state"] == "ok"
    assert health_of({**meta, "tagged_papers": 80})["state"] == "working"


def test_click_through_filters_reach_the_api(client):
    for qs in ("rungs=1,2", "tissue=liver", "model_type=cell_line",
               "entered_from=2024-01-01&entered_to=2025-01-01", "polymers=PS,PE"):
        assert client.get("/api/papers?" + qs).status_code == 200, qs


def test_click_through_filters_reach_the_api(client):
    for qs in ("rungs=1,2", "tissue=liver", "model_type=cell_line",
               "entered_from=2024-01-01&entered_to=2025-01-01", "polymers=PS,PE"):
        assert client.get("/api/papers?" + qs).status_code == 200, qs


def test_every_papers_column_sorts(client):
    for col in ("pmid", "year", "title", "journal", "polymers", "organ_systems", "rungs",
                "model_type", "confidence"):
        for d in ("asc", "desc"):
            assert client.get(f"/api/papers?sort={col}&dir={d}").status_code == 200, (col, d)


def test_the_sankey_other_nodes_filter(client):
    for qs in ("disease_notin=liver_disease", "pathway_notin=oxidative_stress", "polymer_notin=PS,PE"):
        assert client.get("/api/papers?" + qs).status_code == 200, qs


def test_new_this_week_shows_only_on_the_plain_papers_tab(client):
    assert 'id="card-newweek"' in client.get("/papers").get_data(as_text=True)
    assert 'id="card-newweek"' not in client.get("/papers?polymer=PET").get_data(as_text=True)
