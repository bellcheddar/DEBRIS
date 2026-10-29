# DEBRIS findings

Generated from `data/debris.sqlite` on 2026-10-29 18:48 UTC. Regenerate with `pixi run findings`.

DEBRIS indexes what the literature reports. A tag records a polymer detected, an association observed or a mechanism shown; nothing here asserts that plastics cause disease in people. The evidence rungs are ordered so a reader can see how far from a human outcome each claim sits.

## Corpus

Two PubMed strategies, unioned, each PMID keeping the strategies that found it. `PET[tiab]` is never searched on its own, because it returns positron emission tomography.

| Strategy | PMIDs |
|---|---|
| A, MeSH terms | 5,020 |
| B, title and abstract words | 6,573 |
| Negative controls | 402 |
| Found by both A and B | 1,826 |
| **Union harvested** | **10,133** |

### By year

The twelve most recent years; the corpus reaches back to 2004.

| Year | Harvested | DOI verified |
|---|---|---|
| 2027 | 10 | 10 |
| 2026 | 2,266 | 2,242 |
| 2025 | 1,558 | 1,537 |
| 2024 | 1,310 | 1,295 |
| 2023 | 974 | 957 |
| 2022 | 739 | 730 |
| 2021 | 454 | 447 |
| 2020 | 323 | 319 |
| 2019 | 198 | 191 |
| 2018 | 172 | 161 |
| 2017 | 133 | 124 |
| 2016 | 169 | 158 |

## Verification funnel

A paper is admitted when Crossref resolves its DOI and `token_set_ratio` between the PubMed and Crossref titles, case-folded, is at least 90. Only verified papers are counted in the charts; the Papers tab has an "include unverified" switch, off by default.

| DOI status | Papers | Share | Retracted |
|---|---|---|---|
| verified | 9,685 | 95.6% | 13 |
| missing | 248 | 2.4% | 0 |
| title_mismatch | 134 | 1.3% | 0 |
| unresolved | 66 | 0.7% | 0 |

9,685 papers are verified. 362 of those were harvested on purpose as negative controls, positron emission tomography and CT work above all, so that the tagger can be shown refusing them; they are not part of the corpus and are excluded from every count the site publishes, which leaves 9,323. 404 have no abstract, so they are stored but never tagged. 13 are flagged retracted by a Crossref `update-to` relation: they are struck through in the app and never deleted.

## Tagger

`debris_v1` is a single LoRA fine-tune of `Qwen/Qwen2.5-3B-Instruct`, trained once on the task and the schema rather than on facts. The weekly refresh never retrains it. Validation loss ran 2.429 to 0.82 over 1600 iterations. Scored on the held-out split of 162 papers, which no training or validation step saw.

| Field | Fused | Floor | Meets floor | q4 |
|---|---|---|---|---|
| `relevant_f1` | 0.9711 | 0.95 | yes | 0.948 |
| `polymers_f1` | 0.8701 | 0.85 | yes | 0.8111 |
| `organ_systems_f1` | 0.8043 | 0.85 | **no** | 0.6704 |
| `pathways_f1` | 0.6332 | 0.75 | **no** | 0.5363 |
| `rungs_exact` | 0.8457 | 0.7 | yes | 0.7346 |
| `rungs_within_one` | 0.8642 | 0.9 | **no** | 0.7469 |
| `model_type_accuracy` | 0.8523 | 0.9 | **no** | 0.7841 |
| `valid_json` | 1.0 | 0.98 | yes | 0.9877 |

Below floor: organ_systems_f1 0.804 < 0.85; pathways_f1 0.633 < 0.75; rungs_within_one 0.864 < 0.9; model_type_accuracy 0.852 < 0.9. Full card in `MODEL_CARD.md`; the run and its loss curve are in wandb (offline under `wandb/` while no API key is set).

## PET share by organ system

No papers are tagged yet.

## Pathways

No papers are tagged yet.

## Gold controls

Nine papers chosen before the tagger existed, each with an expected outcome. They are tagged by the same pass as everything else, so this table is a standing check that the headline papers are still found and still read correctly.

| Control | PMID | Relevance | Polymers | Organ systems | Rungs | PET | Confidence |
|---|---|---|---|---|---|---|---|
| `blood_detection` | 35367073 | not tagged | none | none | none | no | - |
| `brain_accumulation` | 39901044 | not tagged | none | none | none | no | - |
| `broad_review` | 38460665 | not tagged | none | none | none | no | - |
| `carotid_plaque_cohort` | 38446676 | not tagged | none | none | none | no | - |
| `colorectal_1` | 40602120 | not tagged | none | none | none | no | - |
| `colorectal_2` | 30176444 | not tagged | none | none | none | no | - |
| `lung_tissue` | 35364151 | not tagged | none | none | none | no | - |
| `pet_leachate` | 37755792 | not tagged | none | none | none | no | - |
| `placenta_detection` | 33395930 | not tagged | none | none | none | no | - |

## Vocabulary candidates

When the tagger reaches for a term the controlled vocabulary does not hold, it records `other:<term>` and the paper goes to the review queue rather than being published with an invented tag. The Venn, body map and pathway hub are fixed on the vocabulary in `config/vocab.toml`, so adding any of these is a human decision, not something the pipeline does on its own.

| Field | Proposed value | Papers |
|---|---|---|
| pathways | `lipid_metabolism` | 16 |
| pathways | `er_stress_autophagy` | 14 |
| pathways | `endocrine_disruption` | 8 |
| pathways | `protein_corona` | 7 |
| polymers | `acrylonitrile butadiene styrene` | 2 |
| pathways | `epigenetic_change` | 2 |
| pathways | `insulin_resistance` | 2 |
| polymers | `pcl` | 1 |
| polymers | `pha` | 1 |
| polymers | `polyacrylonitrile` | 1 |
| polymers | `polyglycolic acid` | 1 |

## Research gaps

No papers are tagged yet.

## Operations

|  |  |
|---|---|
| Inference path | A, the Hugging Face ZeroGPU Space |
| Model version | debris_v1 |
| Weights | `data/adapters/debris_v1_fused` |
| Next scheduled run | Sunday 2026-11-01 at 02:00 local, `com.mdeller.debris.weekly.plist` |
| Review queue | 0 |
| Last run | `harvest-20261029T065911Z`, in progress |

The refresh runs weekly and never retrains: it harvests the last seven days by `EDAT`, verifies the DOIs, tags the new papers with `debris_v1`, scores novelty, rebuilds the JSON bundles and pushes data to the droplet. A re-run over the same week adds nothing.
