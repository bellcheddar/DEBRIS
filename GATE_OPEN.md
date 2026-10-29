# G1 Blocked: the droplet's weekly timer needs disabling and I cannot do it

Raised 2026-10-29 05:05. The build is not blocked; everything else continues.

## What is wrong

`debris-weekly.timer` is enabled and active on the droplet and fires every Sunday at
02:15 UTC. It runs `pipeline.weekly --remote`, which is path A: tagging through the
Hugging Face ZeroGPU Space. There is no `HF_TOKEN` on the droplet and no mlx or GPU
there, so the tag stage cannot run. Because the weekly runner logs a failed stage and
carries on, the droplet would harvest and verify new papers, leave them untagged, and
rebuild its own JSON bundles from its own database.

The spec wants one timer, and the live one is the Studio's launchd job
(`com.mdeller.debris.weekly`, installed and enabled today, next firing Sunday
2026-11-01 02:00 local). That job tags with the local model and pushes the result with
`deploy.sh --data-only`. With both timers running, the droplet would diverge from the
Studio for the hours between the two firings and then be overwritten.

Nothing is lost either way: the Studio push replaces the database and the bundles
wholesale. The cost is a live site showing a half-refreshed corpus for part of Sunday.

## What I have already done

`deploy/provision.sh` no longer enables the timer unconditionally. It enables it only
when the droplet's `.env` carries an `HF_TOKEN`, and otherwise installs the unit and
leaves it disabled with a line saying the Studio job is the live timer. So a fresh
provision is correct. The droplet as it stands was provisioned before that fix.

## What I need

One command, on the droplet:

    ssh root@45.55.102.228 'systemctl disable --now debris-weekly.timer'

My own attempt was refused by the auto mode classifier as a remote shell write, twice,
and I have not tried to route the same change through `deploy.sh --provision`: that would
reprovision the host, restart gunicorn and touch the certificate to achieve one line, and
it would be working around the refusal rather than respecting it.

Either run it, or allow remote shell writes and tell me, and I will.

## Checking it afterwards

    ssh root@45.55.102.228 'systemctl is-enabled debris-weekly.timer; systemctl is-active debris-weekly.timer'

Both should answer `disabled` and `inactive`. The unit files stay in place, so switching
to path A later is `systemctl enable --now debris-weekly.timer` once a token is in
`/opt/debris/.env`.
