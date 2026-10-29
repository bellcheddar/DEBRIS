#!/bin/bash
# One-shot launcher for the unattended DEBRIS build. Export any of
# ANTHROPIC_API_KEY NCBI_API_KEY WANDB_API_KEY HF_TOKEN before running; all are optional.
cd "$(dirname "$0")" || exit 1
# Install the scoped permissions (the remote tools cannot write into .claude/ directly).
mkdir -p .claude && cp -n claude_settings.json .claude/settings.json
chmod +x launch.sh
tmux new -d -s debris 'claude "Read DEBRIS_BUILD_SPEC.md and execute it end to end under Section 0. Deploy is pre-approved."'
echo "Build started in tmux session 'debris'. Attach with: tmux attach -t debris"
