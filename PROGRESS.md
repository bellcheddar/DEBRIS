# DEBRIS progress

Rewritten after every phase and at least every 30 minutes during compute.

## Phase 1 Corpus (100 %)

- [x] Reuse map scanned and recorded in REUSE.md
- [x] pixi environment (python 3.12, mlx-lm 0.29.1, Metal available) and uv app venv
- [x] `tools/hwprobe.py` -> config/hardware.toml, config/tuning.toml (M2 Ultra, 128 GB, 60 GPU cores)
- [x] `pipeline/harvest.py`: 10,132 PMIDs (MeSH 5,020, text word 6,573, 402 negatives, 9/9 gold)
- [x] `pipeline/verify_doi.py`: Crossref funnel, case-folded title match, retraction flag
- [x] SQLite schema with every index, `papers` populated
- [x] Elora design system, four tabs, Papers tab live with the untagged corpus
- [x] `pipeline/aggregate.py` and the five static bundles
- [x] 57 tests green (schema, DOI with mocked HTTP, aggregate totals vs SQL, novelty, routes)
- [x] Bootstrap labels (1,600: 868 relevant, 732 not) and the wandb dataset artifact (offline)
- [x] Phase 1 deploy to debris.mdeller.com (live over HTTPS, ingest banner shown)

## Phase 2 Tagger (70 %)

- [x] `pipeline/tag.py` (local mlx and remote Space paths, priority tiers, review queue)
- [x] `pipeline/train.py` (LoRA, fuse, q4, field-by-field scoring, model card, wandb)
- [x] `pipeline/novelty.py`, `pipeline/validate.py`, `pipeline/drift.py`, `tools/smoke_test.py`
- [x] `hf/space/app.py` and `hf/push_model.py` written, ready for a token
- [x] Bootstrap labels written, canonicalised, split 1,277/161/162, logged to wandb
- [x] Smoke test: 11.2 papers/min, 10.6 h projected for 7,113 untagged, inside the 24 h budget
- [x] Training run: debris_v1, LoRA 800 iterations in 53.5 min, validation loss 0.813 to 0.765
- [x] Stale 5.x transformers files cleared from the pixi environment (D15), train stages resumable
- [ ] Fuse, q4 convert and the 5.5 acceptance floor on the 162-paper test split
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
- [ ] Timer installed and enabled on the droplet, dry weekly run
- [ ] README, FINDINGS.md

Open gates: none
