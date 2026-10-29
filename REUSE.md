# DEBRIS reuse log

Every lift from a sibling project under `/Users/dellboy/Documents/Vibe_Coding/`.
Files are copied into `debris/` and adapted; nothing is imported across project
folders and no sibling project is modified (spec section 3).

| Need | Source | Destination | What changed |
|---|---|---|---|
| Hardware probe and derived tuning | `KINFOLK/tools/hwprobe.py` | `tools/hwprobe.py` | Fold/MPS settings replaced by mlx tagger settings (`model_id`, `tag_batch_size`, `ncbi_rate_per_second`); `torch.backends.mps` check replaced by `mlx.core.metal.is_available()` |
| pixi workspace shape, task table, activation env | `KINFOLK/pixi.toml` | `pixi.toml` | Structural-biology dependency set replaced by the harvest/tag/serve set; tasks renamed to the DEBRIS pipeline stages |
| Manifest read/write and resumable-stage pattern | `KINFOLK/pipeline`, `BINMAN/data/manifests` convention | `pipeline/common.py` | Generalised to `manifest_write`/`manifest_read`/`manifest_done`; one JSONL per stage under `data/manifests/` |
| tenacity-wrapped HTTP with a process-wide rate limiter | `KINFOLK` fetch helpers | `pipeline/common.py` (`http_get`, `RateLimiter`) | Retries on 429 and 5xx only; DEBRIS User-Agent with Marc's mailto for the Crossref and NCBI polite pools |
| Droplet deploy by rsync then service restart, nginx vhost, systemd web service, weekly timer and oneshot service, provision script | `AlphaFraud/deploy/*` | `deploy/*` | Names, paths and port changed to debris/8014; weekly service runs `pipeline/weekly.py`; `--data-only` flag added for the weekly data swap; droplet SSH target read from `AlphaFraud/.env` (`root@45.55.102.228`) and recorded in `config/deploy.toml` |
| Droplet SSH target and path convention | `AlphaFraud/.env` | `config/deploy.toml` | Copied host, user and `/opt/<app>` layout; new `SERVER_NAME=debris.mdeller.com`, `BIND_ADDR=127.0.0.1:8014` |
| nginx static-asset block with long-cache snippet and gzip types | `AlphaFraud/deploy/nginx-alphafraud.conf`, droplet `/etc/nginx/sites-available/codswallop` | `deploy/nginx.debris.conf` | Static alias points at `app/static/`; the long-cache snippet already on the droplet is included rather than duplicated |
| gunicorn config | `AlphaFraud/deploy/gunicorn.conf.py` | `deploy/gunicorn.conf.py` | Bind address and worker count for the DEBRIS read-only workload |
| mlx-lm LoRA train, fuse and convert wrapper, chat-format JSONL preparation, model card writer | `chatMCD/train`, `chatMCD/scripts/model_card.py` | `pipeline/train.py`, `MODEL_CARD.md` writer | System prompt and schema replaced by the DEBRIS tagger prompt; wandb logging added; acceptance floor from spec 5.5 |
| ZeroGPU Gradio Space with `@spaces.GPU` and a `gradio_client` caller | `chatMCD/space/app.py` | `hf/space/app.py`, `pipeline/tag.py` (`--remote`) | Chat UI replaced by a batched `tag(batch)` endpoint returning validated JSON plus self-consistency |
| Flask tab layout, Tabulator table, detail drawer, `/healthz`, vendored Plotly with `?v=<mtime>` cache busting | `CODSWALLOP`, `AlphaFraud/alphafraud` | `app/` | Design system swapped for Elora (spec 6.2); four DEBRIS tabs; no request-time compute (all chart data pre-aggregated to `app/static/data/*.json`) |
| Icon house style and favicon set | `marcs-vibe-icon` skill | `icons/` | DEBRIS mark in Elora blue `#385098` |
| README house standard | `marcs-vibe-coding` skill (`readme_forge`) | `README.md` | DEBRIS content |

## 14. Commented version bound on transformers

Source: `chatMCD/space/requirements.txt`, which carries `transformers>=4.51` with the
reason written beside it ("Qwen3 support landed in 4.51"). chatMCD pins a floor only, so
the bound itself is not reusable; what was lifted is the habit of recording why a version
bound exists next to the bound. DEBRIS needs a ceiling instead (`>=4.48,<5`, see
DECISIONS.md D13) because mlx-lm 0.29 cannot read transformers 5's chat-template return
value. Nothing was copied from the sibling and nothing in it was modified.

## 15. readme_forge.py

Source: `/Users/dellboy/Documents/Vibe_Coding/marcs-vibe-coding/scripts/readme_forge.py`,
copied unchanged to `scripts/readme_forge.py`. It polishes a crude README into the house
format (branded header, shields, section emoji, author footer) and emits the Elementor
HTML. DEBRIS supplies `readme_meta.json` with the tagline and the "why it matters"
paragraph, which the script cannot invent. The sibling was not modified and nothing is
imported across folders.
