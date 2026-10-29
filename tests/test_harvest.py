"""Parsing a PubMed record, and choosing the gold controls."""
from __future__ import annotations

import xml.etree.ElementTree as ET

from pipeline import harvest

ARTICLE = """
<PubmedArticle>
  <MedlineCitation>
    <PMID>39901044</PMID>
    <Article>
      <Journal><ISOAbbreviation>Nat Med</ISOAbbreviation>
        <JournalIssue><PubDate><Year>2025</Year><Month>Feb</Month></PubDate></JournalIssue>
      </Journal>
      <ArticleTitle>Bioaccumulation of microplastics in decedent human brains.</ArticleTitle>
      <Abstract><AbstractText Label="METHODS">Brain tissue was digested.</AbstractText></Abstract>
      <AuthorList><Author><LastName>Nihart</LastName><Initials>AJ</Initials></Author></AuthorList>
      <PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList>
    </Article>
  </MedlineCitation>
  <PubmedData>
    <ArticleIdList>
      <ArticleId IdType="pubmed">39901044</ArticleId>
      <ArticleId IdType="doi">10.1038/s41591-024-03453-1</ArticleId>
    </ArticleIdList>
    <ReferenceList>
      <Reference>
        <ArticleIdList><ArticleId IdType="doi">10.5334/aogh.4056</ArticleId></ArticleIdList>
      </Reference>
      <Reference>
        <ArticleIdList><ArticleId IdType="doi">10.1016/j.jhazmat.2021.127237</ArticleId></ArticleIdList>
      </Reference>
    </ReferenceList>
  </PubmedData>
</PubmedArticle>
"""


def test_the_doi_comes_from_the_record_not_from_its_citations():
    """A descendant search once took the last DOI in the record, which was a cited
    paper's, so this article was stored under a commission report's DOI."""
    rec = harvest.parse_article(ET.fromstring(ARTICLE))
    assert rec["doi"] == "10.1038/s41591-024-03453-1"


def test_the_labelled_abstract_and_metadata_survive():
    rec = harvest.parse_article(ET.fromstring(ARTICLE))
    assert rec["pmid"] == "39901044"
    assert rec["year"] == 2025
    assert rec["journal"] == "Nat Med"
    assert "METHODS" in rec["abstract"]
    assert rec["pub_types"] == ["Journal Article"]


def test_an_elocation_doi_is_used_when_the_id_list_has_none():
    xml = ARTICLE.replace('<ArticleId IdType="doi">10.1038/s41591-024-03453-1</ArticleId>', "")
    xml = xml.replace("</Abstract>",
                      '</Abstract><ELocationID EIdType="doi">10.1/fallback</ELocationID>')
    assert harvest.parse_article(ET.fromstring(xml))["doi"] == "10.1/fallback"


# ------------------------------------------------------------- gold control choice

def record(pmid, title, abstract="an abstract", types=("Journal Article",)):
    return {"pmid": pmid, "title": title, "abstract": abstract, "pub_types": list(types)}


def test_a_comment_never_stands_in_for_the_paper_it_comments_on():
    """The blood control resolved to a letter about Leslie et al., not the paper."""
    hits = [record("35932534", "Letter to the editor, discovery of plastic particles",
                   abstract="", types=("Letter", "Comment")),
            record("35367073", "Discovery and quantification of plastic particle "
                               "pollution in human blood")]
    entry = {"key": "blood_detection", "title_must_match": "human blood"}
    chosen = harvest.gold_candidate(entry, hits, [r["pmid"] for r in hits])
    assert chosen["pmid"] == "35367073"


def test_a_title_that_does_not_match_is_rejected():
    hits = [record("1", "Properties of polyethylene terephthalate after thermo-oxidation")]
    entry = {"key": "pet_leachate", "title_must_match": "toxicological"}
    assert harvest.gold_candidate(entry, hits, ["1"]) is None


def test_a_review_control_takes_the_review():
    hits = [record("1", "Human health effects of plastics: a primary study"),
            record("2", "Human health effects of plastics", types=("Journal Article", "Review"))]
    entry = {"key": "broad_review", "prefer": "review", "title_must_match": "human health"}
    assert harvest.gold_candidate(entry, hits, ["1", "2"])["pmid"] == "2"


def test_a_review_type_does_not_disqualify_a_primary_paper_on_its_own():
    """PubMed types Ragusa's placenta paper as a Review; rejecting it outright lost the
    control, so the preference ranks rather than rejects."""
    hits = [record("33395930", "Plasticenta: first evidence of microplastics in human placenta",
                   types=("Journal Article", "Review"))]
    entry = {"key": "placenta_detection", "title_must_match": "placenta"}
    assert harvest.gold_candidate(entry, hits, ["33395930"])["pmid"] == "33395930"
