# DEBRIS lab report

Generated 2026-10-30T00:18:30+00:00 by `pixi run lab report` from the predictions under `data/lab/`. The plan and the rules for adopting an idea are in LAB_PLAN.md. Every interval is a 95 % paired bootstrap over papers (2000 resamples); `floor_mean` is the plain mean of the eight floor metrics.

## Experiments

| experiment | round | papers | relevant_f1 | polymers_f1 | organ_systems_f1 | pathways_f1 | rungs_exact | rungs_within_one | model_type_accuracy | valid_json | floor_mean |
|---|---|---|---|---|---|---|---|---|---|---|---|
| phase0-baseline | round07 | 1438 | 0.873 ±0.018 | 0.762 ±0.028 | 0.662 ±0.024 | 0.563 ±0.024 | 0.738 ±0.023 | 0.791 ±0.021 | 0.719 ±0.032 | 1.000 ±0.000 | 0.764 ±0.014 |

## Phase 0: learning curve, fold 0

| iteration | relevant_f1 | polymers_f1 | organ_systems_f1 | pathways_f1 | rungs_exact | rungs_within_one | model_type_accuracy | valid_json | floor_mean |
|---|---|---|---|---|---|---|---|---|---|
| 200 | 0.894 | 0.758 | 0.651 | 0.523 | 0.602 | 0.812 | 0.727 | 1.000 | 0.746 |
| 400 | 0.895 | 0.776 | 0.656 | 0.512 | 0.800 | 0.838 | 0.719 | 1.000 | 0.775 |
| 600 | 0.892 | 0.774 | 0.695 | 0.579 | 0.785 | 0.842 | 0.731 | 1.000 | 0.787 |
| 800 | 0.901 | 0.753 | 0.669 | 0.565 | 0.767 | 0.808 | 0.758 | 1.000 | 0.778 |

