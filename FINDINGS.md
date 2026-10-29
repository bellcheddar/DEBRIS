# DEBRIS findings

Generated from `data/debris.sqlite` on 2026-10-29 06:46 UTC. Regenerate with `pixi run findings`.

DEBRIS indexes what the literature reports. A tag records a polymer detected, an association observed or a mechanism shown; nothing here asserts that plastics cause disease in people. The evidence rungs are ordered so a reader can see how far from a human outcome each claim sits.

## Corpus

Two PubMed strategies, unioned, each PMID keeping the strategies that found it. `PET[tiab]` is never searched on its own, because it returns positron emission tomography.

| Strategy | PMIDs |
|---|---|
| A, MeSH terms | 5,020 |
| B, title and abstract words | 6,573 |
| Negative controls | 402 |
| Found by both A and B | 1,826 |
| **Union harvested** | **10,132** |

### By year

The twelve most recent years; the corpus reaches back to 2004.

| Year | Harvested | DOI verified |
|---|---|---|
| 2027 | 10 | 8 |
| 2026 | 2,266 | 1,482 |
| 2025 | 1,558 | 1,053 |
| 2024 | 1,310 | 989 |
| 2023 | 974 | 710 |
| 2022 | 739 | 552 |
| 2021 | 453 | 351 |
| 2020 | 323 | 266 |
| 2019 | 198 | 169 |
| 2018 | 172 | 142 |
| 2017 | 133 | 110 |
| 2016 | 169 | 147 |

## Verification funnel

A paper is admitted when Crossref resolves its DOI and `token_set_ratio` between the PubMed and Crossref titles, case-folded, is at least 90. Only verified papers are counted in the charts; the Papers tab has an "include unverified" switch, off by default.

| DOI status | Papers | Share | Retracted |
|---|---|---|---|
| verified | 7,427 | 73.3% | 11 |
| title_mismatch | 2,368 | 23.4% | 3 |
| missing | 248 | 2.4% | 0 |
| unresolved | 89 | 0.9% | 0 |

7,427 papers are verified. 404 have no abstract, so they are stored but never tagged. 14 are flagged retracted by a Crossref `update-to` relation: they are struck through in the app and never deleted.

## Tagger

The tagger has not been scored yet; see `MODEL_CARD.md` once `pixi run train` has finished.

## PET share by organ system

No papers are tagged yet.

## Pathways

No papers are tagged yet.

## Gold controls

Nine papers chosen before the tagger existed, each with an expected outcome. They are tagged by the same pass as everything else, so this table is a standing check that the headline papers are still found and still read correctly.

| Control | PMID | Relevance | Polymers | Organ systems | Rungs | PET | Confidence |
|---|---|---|---|---|---|---|---|
| `blood_detection` | 35932534 | not tagged | none | none | none | no | - |
| `brain_accumulation` | 41233598 | not tagged | none | none | none | no | - |
| `broad_review` | 38460665 | not tagged | none | none | none | no | - |
| `carotid_plaque_cohort` | 38446676 | not tagged | none | none | none | no | - |
| `colorectal_1` | 40602120 | not tagged | none | none | none | no | - |
| `colorectal_2` | 39272937 | not tagged | none | none | none | no | - |
| `lung_tissue` | 35364151 | not tagged | none | none | none | no | - |
| `pet_leachate` | 38587644 | not tagged | none | none | none | no | - |
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
| Inference path | B, the mlx model on the Studio (no HF_TOKEN present) |
| Model version | debris_v1 |
| Weights | `data/adapters/debris_v1_q4` |
| Next scheduled run | Sunday 2026-11-01 at 02:00 local, `com.mdeller.debris.weekly.plist` |
| Review queue | 0 |
| Last run | `harvest-20261029T034957Z`, in progress |

The refresh runs weekly and never retrains: it harvests the last seven days by `EDAT`, verifies the DOIs, tags the new papers with `debris_v1`, scores novelty, rebuilds the JSON bundles and pushes data to the droplet. A re-run over the same week adds nothing.
