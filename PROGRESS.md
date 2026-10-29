# DEBRIS progress

Rewritten after every phase and at least every 30 minutes during compute.

## Phase 1 Corpus (100 %)

- [x] Reuse map scanned and recorded in REUSE.md
- [x] pixi environment (python 3.12, mlx-lm 0.29.1, Metal available) and uv app venv
- [x] `tools/hwprobe.py` -> config/hardware.toml, config/tuning.toml (M2 Ultra, 128 GB, 60 GPU cores)
- [x] `pipeline/harvest.py`: 10,132 PMIDs (MeSH 5,020, text word 6,573, 402 negatives, 9/9 gold)
- [x] `pipeline/verify_doi.py`: Crossref funnel, case-folded title match, retraction flag
- [x] DOI parser corrected (D20): the stored DOI was sometimes a cited paper's; corpus re-harvested
- [x] Gold controls pinned and corrected (D19): three of nine were the wrong paper
- [x] SQLite schema with every index, `papers` populated
- [x] Elora design system, four tabs, Papers tab live with the untagged corpus
- [x] `pipeline/aggregate.py` and the five static bundles
- [x] 77 tests green (schema, DOI with mocked HTTP, aggregate totals vs SQL, novelty, routes)
- [x] Bootstrap labels (1,600: 868 relevant, 732 not) and the wandb dataset artifact (offline)
- [x] Phase 1 deploy to debris.mdeller.com (live over HTTPS, ingest banner shown)

## Phase 2 Tagger (80 %)

- [x] `pipeline/tag.py` (local mlx and remote Space paths, priority tiers, review queue)
- [x] `pipeline/train.py` (LoRA, fuse, q4, field-by-field scoring, model card, wandb)
- [x] `pipeline/novelty.py`, `pipeline/validate.py`, `pipeline/drift.py`, `tools/smoke_test.py`
- [x] `hf/space/app.py` and `hf/push_model.py` written, ready for a token
- [x] Bootstrap labels written, canonicalised, split 1,277/161/162, logged to wandb
- [x] Smoke test: 11.2 papers/min, 10.6 h projected for 7,113 untagged, inside the 24 h budget
- [x] Training run: debris_v1, LoRA 800 iterations in 53.5 min, validation loss 0.813 to 0.765
- [x] Stale 5.x transformers files cleared from the pixi environment (D15), train stages resumable
- [x] Fused and q4 converted; q4 lost 15 F1 points on relevance, so `USE_FUSED` is set
- [x] Fuse and quantise split into separately resumable stages (D21), so a convert that
      refuses an existing directory no longer costs the fine-tune
- [x] Error breakdown by field (`pixi run errors`) over the recorded test-split predictions
- [x] Labels repaired (D22): `model_type` was arbitrary on all 732 irrelevant papers and
      144 rung-5 labels sat on abstracts reporting no dose; the split is now frozen
- [x] Repaired labels retrained: relevant_f1 0.9600 clears its floor, rungs_exact 0.8148,
      valid_json 1.0; polymers 0.8152, organs 0.7591, pathways 0.6644, rungs within one
      0.8580 and model_type 0.8523 still short
- [x] Checkpoint choice measured on the validation split, not on validation loss (D24):
      the lowest-loss checkpoint was worse on every field
- [x] 32-layer rung (D25): four of eight floors now clear, polymers 0.8701 and relevant
      0.9711 among them; archived as data/adapters/debris_v1_32layer1600
- [x] The two stubborn metrics measured rather than guessed (D25): model_type is limited by
      a cell_line / human_in_vitro boundary the labels do not hold to, and pathways is
      over-prediction on oxidative_stress as much as missed barrier_disruption signal
- [ ] The 5.5 acceptance floor: organs 0.804, pathways 0.633, rungs within one 0.864 and
      model_type 0.852 short; Qwen2.5-7B rung running (then G2 for what is label-limited)
- [ ] Full corpus tagged

## Phase 3 App polish (85 %)

- [x] Atlas (Venn, evidence ladder, year series), Body (SVG map), Pathways (Sankey, radar), Papers (feed, Tabulator, drawer)
- [x] Icons and favicon set, self-hosted Montserrat and IBM Plex Mono
- [x] `tools/qc_ui.py`: 8 page renders, 0 serious or critical axe violations, 0 console errors
- [x] Atlas interactive in 0.59 s against the 1.5 s budget; both click-throughs working
- [ ] QC re-run against the tagged corpus, chart totals reconciled against SQL

## Phase 4 Weekly, QC, delivery (40 %)

- [x] `pipeline/weekly.py`, `deploy/weekly.sh`, systemd service and timer, launchd plist
- [x] `deploy/deploy.sh` (code, data, `--data-only`, `--provision`), nginx vhost, provision script
- [x] Studio launchd timer installed and enabled, next firing Sunday 2026-11-01 02:00;
      it covers this Sunday and is retired the moment path A is proven
- [x] Droplet timer disabled and verified (D23): disabled, inactive, off the timer list
- [x] Path A chosen (D26) and its credential in place (D27): fine-grained `debris` token
      with no expiry, private model repo created, token on the droplet at mode 600
- [ ] Path A switchover, once the ladder picks a model: push the fused model and the
      private Space, verify it tags a real abstract, enable debris-weekly.timer and
      disable the Studio launchd job in the same step, then a dry weekly run
- [ ] Dry weekly run
- [x] `tools/findings.py` and `tools/readme.py`, both generated from the database and the forge
- [ ] Final README and FINDINGS.md regenerated against the tagged corpus

Open gates: none.
