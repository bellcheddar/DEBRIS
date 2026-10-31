"""The rosters are data, and these tests are what keeps them honest.

The Atlas panels and the body map are built entirely from config/vocab.toml: the polymer
order, the short names, the chemical families, and every anatomical site with its anchor
and its organ drawing. Going from 13 polymers to 11, or from 13 tissues to 18, should be
an edit to that file alone. Each of these tests is one way that could quietly fail.
"""
from __future__ import annotations

import re

from pipeline import aggregate
from pipeline import common as c

V = c.vocab()
ANATOMY = (c.ROOT / "app" / "templates" / "_anatomy.html").read_text()
DRAWN = set(re.findall(r'data-art="([^"]+)"', ANATOMY))


def test_every_polymer_has_a_family_a_short_name_and_a_label():
    for polymer in V["polymers"]:
        assert polymer in V["polymer_families"], f"{polymer} has no chemical family"
        assert polymer in V["polymer_short"], f"{polymer} has no short name for a chart"
        assert polymer in V["polymer_labels"], f"{polymer} has no label"


def test_every_polymer_has_a_colour_token():
    """A polymer with no --poly-<key> token falls back to grey and becomes invisible
    among the others, which is worse than it being obviously wrong."""
    css = (c.ROOT / "app" / "static" / "css" / "theme.css").read_text()
    for polymer in V["polymers"]:
        assert f"--poly-{polymer}:" in css, f"{polymer} has no colour token"


def test_short_names_are_short_enough_to_draw():
    """The matrix and the bars label their axes with these, in a fixed gutter."""
    for polymer, short in V["polymer_short"].items():
        assert len(short) <= 5, f"{polymer} short name {short!r} will not fit the axis"


def test_every_organ_system_is_somewhere_on_the_body():
    """A system with no site is a system whose papers never appear on the map. Systemic
    had exactly that problem: it was not absent from the corpus, only from the picture."""
    sited = {organ for node in V["body_nodes"] for organ in node.get("organs", [])}
    missing = [o for o in V["organ_systems"] if o not in sited]
    assert not missing, f"no anatomical site counts these organ systems: {missing}"


def test_every_body_node_has_a_drawing():
    for node in V["body_nodes"]:
        assert node["art"] in DRAWN, f"{node['key']} points at art {node['art']!r}, not drawn"


def test_every_drawing_belongs_to_a_node():
    """An organ nobody can select is decoration the reader will try to click."""
    claimed = {node["art"] for node in V["body_nodes"]}
    assert not (DRAWN - claimed), f"drawn but unreachable: {sorted(DRAWN - claimed)}"


def test_every_anchor_lands_on_the_figure():
    """The anchors are in the 360 x 720 space the silhouette is drawn in."""
    for node in V["body_nodes"]:
        assert 0 <= node["x"] <= 360, f"{node['key']} x={node['x']} is off the figure"
        assert 0 <= node["y"] <= 720, f"{node['key']} y={node['y']} is off the figure"


def test_body_nodes_carry_what_the_panels_need(corpus):
    conn = c.connect(corpus)
    bundle = aggregate.body_bundle(conn)
    assert len(bundle["nodes"]) == len(V["body_nodes"])
    for node in bundle["nodes"]:
        for field in ("key", "label", "organs", "x", "y", "region", "art", "count",
                      "pet_count", "max_rung", "mix", "polymers", "pathways", "papers"):
            assert field in node, f"{node.get('key')} is missing {field}"
    assert bundle["regions"], "the cards panel sorts by region"
    conn.close()


def test_a_tissue_polymer_mix_is_a_share_of_its_own_papers(corpus):
    """The cards compare tissues band for band, which only works if each is normalised."""
    conn = c.connect(corpus)
    for node in aggregate.body_bundle(conn)["nodes"]:
        if not node["mix"]:
            continue
        total = sum(m["share"] for m in node["mix"])
        assert 0.0 < total <= 1.0001, f"{node['key']} mix sums to {total}"
    conn.close()


def test_adding_a_tissue_needs_no_code_change(corpus, monkeypatch):
    """The proof that the roster is data: a site the code has never heard of still
    reaches the bundle, counted, as long as the vocabulary names a drawing for it."""
    extra = dict(V["body_nodes"][0], key="spleen", label="Spleen",
                 organs=["immune"], region="Abdomen", art="liver", x=224, y=300)
    monkeypatch.setitem(aggregate.V, "body_nodes", V["body_nodes"] + [extra])
    conn = c.connect(corpus)
    nodes = aggregate.body_bundle(conn)["nodes"]
    added = next(n for n in nodes if n["key"] == "spleen")
    assert added["region"] == "Abdomen" and added["art"] == "liver"
    assert added["count"] == conn.execute(
        """SELECT COUNT(DISTINCT p.pmid) FROM papers p JOIN tags t USING (pmid)
           JOIN tag_organs o ON o.pmid=p.pmid
           WHERE p.doi_status='verified' AND t.relevant=1
             AND COALESCE(p.hit_strategy,'') <> 'negative'
             AND o.organ_system='immune'""").fetchone()[0]
    conn.close()
