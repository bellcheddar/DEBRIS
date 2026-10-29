# DEBRIS

- `DEBRIS_BUILD_SPEC.md` (v2.0) is authoritative. Execute it end to end under Section 0.
- Two gates only (G1 Blocked, G2 Science). Everything else: decide, log to DECISIONS.md, continue.
- Deploy to debris.mdeller.com is pre-approved. Run deploy/deploy.sh at the end of every phase.
- Reuse first: copy from sibling projects under /Users/dellboy/Documents/Vibe_Coding/ (AlphaFraud for droplet deploy and weekly timer, chatMCD and FAFFAbout for mlx-lm training, SEANCE for ZeroGPU, CODSWALLOP for Flask tabs). Record every lift in REUSE.md. Never import across folders, never modify a sibling.
- Keep BUILD_LOG.md, PROGRESS.md and data/manifests/ current; every stage is resumable.
- Commit at the end of each phase and push to origin. Never create repos. Never sudo locally.
- Hardware settings come from config/tuning.toml via tools/hwprobe.py. Nothing hard-coded.
- The app uses the Elora Therapeutics design system (spec 6.2), not the marcdeller.com header.
- The tagger is trained once (debris_v1), tracked in wandb; inference on the Hugging Face ZeroGPU Space (path A) or the Studio via launchd (path B). Weekly runs never retrain.
- wandb, Hugging Face, Anthropic and NCBI keys are all optional; each has a logged fallback.
- British English. No em dashes. Never claim human causation in copy.
