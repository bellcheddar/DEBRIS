"""tools/tag_bench.py: the pure parts, which decide what the bench recommends."""
from tools import tag_bench as tb

TAG = '{"relevant":true,"polymers":["PS"],"confidence":%s}'


def test_answer_key_ignores_confidence_and_whitespace():
    assert tb.answer_key(TAG % "0.9") == tb.answer_key(" " + TAG % "0.4" + "\n")
    assert tb.answer_key("not json") is None


def test_agreement_counts_unparsed_as_disagreement():
    assert tb.agreement([TAG % "1", "junk"], [TAG % "0", "junk"]) == 0.5


def test_auc():
    assert tb.auc([0.9, 0.8, 0.1, 0.2], [True, True, False, False]) == 1.0
    assert tb.auc([0.5, 0.5], [True, False]) == 0.5
    assert tb.auc([0.3], [True]) is None


def test_is_prefix():
    assert tb.is_prefix([1, 2], [1, 2, 3])
    assert not tb.is_prefix([1, 2], [1, 2])
    assert not tb.is_prefix([1, 3], [1, 2, 3])


def test_pick_is_the_fastest_arm_that_tags_the_same():
    results = {"batched-8": {"s_per_paper": 0.9, "agreement": 1.0},
               "batched-64": {"s_per_paper": 0.2, "agreement": 0.5},
               "batched-32": {"s_per_paper": 0.4, "agreement": 0.97},
               "batched-16": {"failed": "oom"}}
    assert tb.pick(results, [])["arm"] == "batched-32"
    assert tb.pick({"batched-8": {"failed": "x"}}, []) == {}


def test_answer_key_ignores_free_text_and_list_order():
    a = '{"relevant":true,"pathways":["b","a"],"summary":"one wording","disease_terms":["x"]}'
    b = '{"relevant":true,"pathways":["a","b"],"summary":"another","disease_terms":["y"]}'
    assert tb.answer_key(a) == tb.answer_key(b)
    assert tb.field_agreement([a], [b]) == {"pathways": 1.0, "relevant": 1.0}
