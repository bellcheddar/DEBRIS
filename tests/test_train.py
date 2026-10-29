"""Checkpoint choice: mlx-lm keeps the last adapter, and the best one is chosen on the
validation split field by field rather than on validation loss (D24)."""
from __future__ import annotations

import json

from pipeline import train


def metrics(**over) -> dict:
    base = {"relevant_f1": 0.96, "polymers_f1": 0.82, "organ_systems_f1": 0.76,
            "pathways_f1": 0.66, "rungs_exact": 0.81, "rungs_within_one": 0.86,
            "model_type_accuracy": 0.85, "valid_json": 1.0}
    return {**base, **over}


def test_rank_counts_the_floors_met_first():
    weaker = metrics(relevant_f1=0.90)
    assert train.checkpoint_rank(metrics())[0] == 3
    assert train.checkpoint_rank(weaker)[0] == 2
    assert train.checkpoint_rank(metrics()) > train.checkpoint_rank(weaker)


def test_a_metric_over_its_floor_cannot_pay_for_one_under_it():
    """rungs_exact is already 0.11 over its floor. Pushing it higher must not buy a
    checkpoint the same rank as one that fixed a field still short."""
    padded = metrics(rungs_exact=1.0)
    improved = metrics(pathways_f1=0.72)
    assert train.checkpoint_rank(padded)[1] == train.checkpoint_rank(metrics())[1]
    assert train.checkpoint_rank(improved) > train.checkpoint_rank(metrics())


def test_every_floor_met_ranks_top():
    perfect = {field: floor for field, floor in train.FLOOR.items()}
    assert train.checkpoint_rank(perfect) == (len(train.FLOOR), 1.0)


def test_model_depth_reads_a_local_config(tmp_path):
    """Depth does not follow parameter count: Qwen2.5-3B has 36 layers and the 7B has 28,
    so the layer count has to come from the model being trained."""
    (tmp_path / "config.json").write_text(json.dumps({"num_hidden_layers": 28}))
    assert train.model_depth(str(tmp_path)) == 28


def test_model_depth_is_none_when_it_cannot_be_read(tmp_path):
    """A model with no readable config leaves --num-layers as the caller asked, rather
    than silently adapting a layer count read from somewhere else."""
    assert train.model_depth(str(tmp_path / "absent")) is None
