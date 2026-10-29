# G1 Blocked: path A needs a Hugging Face token that does not expire this week

Raised 2026-10-29 11:35, replacing the G1 that asked for the droplet timer to be
disabled. That one is resolved: the command was run and verified (`disabled`,
`inactive`, absent from `systemctl list-timers`). The build is not blocked by this gate.

## What changed

The timer is wanted on the droplet, not on the Studio. That is path A in spec 5.6 and the
better arrangement, because the droplet is always on and the Mac is not. Recorded as D26.

## What is missing

Path A tags through a Hugging Face ZeroGPU Space, so it needs a token with write scope in
two places: locally, to push the fused model to `Dellboy/debris-tagger-v1` and create the
Space `Dellboy/debris-tagger`, and in `/opt/debris/.env` on the droplet, which is the
switch `deploy/provision.sh` already looks for before it enables `debris-weekly.timer`.

There is no such token on this machine. What is here:

- `~/.cache/huggingface/token` holds an OAuth credential (`hf_o...`) that expires
  2026-11-03. It may well have the scope to push, but it would stop working within the
  week, and the weekly runner logs a failed stage and carries on, so every Sunday after
  that the droplet would publish untagged papers. That is the failure the previous gate
  was raised to prevent, so an expiring credential is not a fix.
- `chatMCD/.env` has the line `HF_TOKEN=` with an empty value.
- `chatMCD/.env.example` and `ALPHABETTI/.env.example` hold `hf_xxxx` placeholders.
- Nothing in `~/.zshrc`, `~/.zprofile` or `~/.config/huggingface`.

The account itself is fine: `Dellboy` is PRO, so the `zero-a10g` hardware in
`config/hf.toml` is available.

## What I need

A fine-grained or classic token with write scope, from
https://huggingface.co/settings/tokens. Write access to repositories is enough; it does
not need org or billing scopes. Then either:

    huggingface-cli login        # paste it at the prompt, nothing lands in the transcript

or put it in a file outside the repo and tell me where, for example
`~/.config/debris/hf.env` as a single `HF_TOKEN=...` line.

I will then push the model and the Space, verify the Space answers a real abstract, put
the token in the droplet's `.env`, enable `debris-weekly.timer`, disable the Studio
launchd job so only one timer remains, and run a dry weekly refresh end to end.

## What happens meanwhile

Nothing waits on this. The 7B training rung is running, the first full tagging of all
9,685 papers is a local job either way (the Space is budgeted at twenty minutes a week in
`config/hf.toml`, which suits a weekly delta of about fifty papers, not a corpus needing
ten to twenty hours of inference), and the site keeps serving.

The Studio launchd job stays enabled until path A is proven, so this Sunday's refresh
still happens. If the token arrives first, path A takes over and the Studio job is
disabled in the same step.
