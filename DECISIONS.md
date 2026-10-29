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
