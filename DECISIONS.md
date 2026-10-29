# DEBRIS decisions

| Date | Decision | Alternatives | Reason | Reverse by |
|---|---|---|---|---|
| 2026-10-28 | Name DEBRIS; merge PLAQUE ladder, BOTTLE body map, LANDFILL pathway hub into one app | Four separate apps | Marc's choice | n/a |
| 2026-10-28 | Qwen2.5-3B-Instruct, one LoRA fine-tune, no retraining | Llama 3.2 3B (gated); retrain weekly | Ungated weights; tagger learns schema not facts | Train debris_v2 via pipeline/train.py |
| 2026-10-28 | Two gates only; deploy pre-approved; keys optional with fallbacks | Six-gate template | Marc asked for a quick automated build | Edit spec Section 0.2 |
| 2026-10-28 | Weekly inference on HF ZeroGPU Space, droplet-side timer (path A); Studio launchd as path B | Studio only | Removes the Studio from the weekly loop | Switch `inference_path` in config |
| 2026-10-29 | Droplet SSH target taken from `AlphaFraud/.env` (`root@45.55.102.228`), app at `/opt/debris` on port 8014 | Ask Marc for SSH details (would have opened G1) | AlphaFraud's deploy config is the documented source (spec section 3); 8011 to 8013 are already taken on the droplet | Edit `config/deploy.toml` |
| 2026-10-29 | Self-host Montserrat and IBM Plex Mono as woff2 under `app/static/fonts/` | Google Fonts CDN links | No third-party request per page load and no layout shift; the CODSWALLOP font script already does it | Swap `fonts.css` for the Google `<link>` |
| 2026-10-29 | Fold case before the Crossref title match | Case-sensitive `token_set_ratio` | PubMed and Crossref disagree on title case often enough to fail real papers at the 90 floor | Drop `.casefold()` in `verify_doi.normalise` |
| 2026-10-29 | Flask added to the pixi env as well as `requirements.txt` | Two separate test commands | One `pixi run test` then covers the pipeline and the app; the droplet still installs only `requirements.txt` | Remove from `pixi.toml` and run app tests under `.venv` |
| 2026-10-29 | Four keys all absent at launch: the build session writes the bootstrap labels, wandb runs offline, NCBI at 3 req/s, weekly inference on path B (Studio launchd) | Wait for keys (would have stalled the build) | Every fallback is the one the spec names in 0.2; `hf/` is still written so path A needs only a token | Export the keys and re-run `pixi run bootstrap api`, `wandb sync`, `hf/push_model.py` |
| 2026-10-29 | Venn region click-through implemented as `polymers=A|B&not_polymers=C,D` on `/api/papers` | A region id understood only by the app | The query is readable, shareable and testable, and the CSV download honours it unchanged | Replace with a region parameter |
| 2026-10-29 | Bulk polymer devices and implants, monomer or additive exposure with no particles, and drugs merely carrying a polymer name (sodium polystyrene sulfonate) are all `relevant = false` | Admit anything the MeSH polymer terms return | The MeSH strategy sweeps in Dacron grafts, PVC occupational chemistry and Kayexalate; DEBRIS is about micro and nanoplastic particles and their leachates. Particulate wear debris from an implant stays relevant | Edit `LABEL_INSTRUCTIONS` in `pipeline/schema.py` and re-label |
| 2026-10-29 | Carotid plaque positive control asserts `polymers ⊇ {PE, PVC}`, not `{PET, PVC}`, and does not assert `pet_specific` | Follow spec section 9 as written | Marfella et al. (NEJM 2024) report polyethylene and a smaller proportion of polyvinyl chloride in carotid atheroma; they do not report PET. Asserting PET would have trained and tested the tagger against the paper | Restore the spec's expectation in `pipeline/validate.py` if the spec is corrected |
| 2026-10-29 | Wildlife surveys and trophic-transfer studies (particle counts in whales, seabirds, fish) are `relevant = false`; controlled exposure experiments with a pathology, oxidative stress, immune or genotoxic endpoint are `relevant = true` in any species | Admit all animal work, or reject all non-mammalian work | Keeps ecological monitoring out of a disease corpus while keeping the mechanistic evidence that rungs 3 to 5 are built from | Edit `LABEL_INSTRUCTIONS` and re-label |

## D11. Label terms canonicalised against config/vocab.toml (2026-10-29)

Late bootstrap batches drifted into near-miss terms that are not in the controlled
vocabulary (`human_observational`, `respiratory_disease`, `atherosclerosis_cvd`,
`reproductive_dysfunction`, `gi_disease`, `ocular`, `musculoskeletal` and others).
`validate()` silently drops unknown values in closed fields, so those labels would have
trained the tagger on empty slots. All 1,600 session labels were rewritten in place with
an explicit mapping: `human_observational -> human_cohort`; `atherosclerosis_cvd ->
atherosclerosis_mace`; `thrombosis_coagulation -> thrombosis`; `gi_disease -> ibd_gut`;
`autoimmune -> immune_dysfunction`; `neurodevelopmental ->
neuroinflammation_neurodegeneration`; `congenital_developmental -> pregnancy_outcomes`;
`respiratory_disease -> pulmonary_fibrosis` where the terms mention fibrosis, interstitial
disease or emphysema, otherwise `copd_asthma`; `heart_failure_fibrosis`,
`musculoskeletal_disease`, `reproductive_dysfunction` and `endocrine_disruption` (as a
disease category) have no home in the 17 categories and became `none`, with the detail
kept in `disease_terms`; organ `ocular -> neurological` (retina is neural tissue) and
`musculoskeletal -> systemic`. Pathways and polymers are open fields, so
`er_stress_autophagy`, `lipid_metabolism`, `endocrine_disruption`, `protein_corona`,
`insulin_resistance`, `epigenetic_change`, `PHA` and `PCL` were written as `other:<term>`
and now surface through `vocab_candidates` for the FINDINGS.md vocabulary section.
The vocabulary itself was not widened: spec 6.x fixes the Venn, body map and pathway hub
on those 14 pathways and 17 disease categories.

## D12. wandb Run.get_url() replaced with Run.url (2026-10-29)

wandb 0.23 removed `Run.get_url()`; `pipeline/bootstrap_labels.py` and `pipeline/train.py`
now read `getattr(run, "url", None) or "offline"` before `finish()`, which also works in
offline mode where no URL exists.

## D13. transformers pinned to the 4.x line (2026-10-29)

`pixi install` had resolved transformers 5.21.0, where `apply_chat_template` returns a
`BatchEncoding` instead of a list of token ids. mlx-lm 0.29.1 feeds that return value
straight into its batcher, so `mlx_lm.lora` died on the first iteration with
`TypeError: int() argument must be ... not 'tokenizers.Encoding'`. Generation was
unaffected, which is why the smoke test passed and only training broke.
`pixi.toml` now pins `transformers = ">=4.48,<5"` (resolved 4.57.6), the line mlx-lm
targets. Alternative considered and rejected: rewriting the splits into mlx-lm's `text`
format so the buggy code path is skipped, which would have hidden the version conflict
from the droplet and weekly runs.
