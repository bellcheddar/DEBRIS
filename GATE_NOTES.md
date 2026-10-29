# Notes (informational, not gates)

## wandb

Runs were recorded locally under `wandb/` because WANDB_API_KEY was absent.
To push them when a key is available:

```bash
export WANDB_API_KEY=...
cd /Users/dellboy/Documents/Vibe_Coding/debris
wandb sync wandb/offline-run-*
```
