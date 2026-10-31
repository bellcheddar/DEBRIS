"""Point the [tag] table of config/tuning.toml at the v2 tagger (D55).

  pixi run python tools/set_tag_recipe.py
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import tomli_w

TUNING = Path(__file__).resolve().parents[1] / "config" / "tuning.toml"


def main() -> int:
    tuning = tomllib.loads(TUNING.read_text())
    tuning.setdefault("tag", {}).update({
        "recipe": "v2", "model": "Qwen/Qwen2.5-3B-Instruct", "adapter": "data/adapters/debris_v2",
        "recipe_status": "owner chose option C 2026-10-30, adopted recipe from Phase 5 (D55)"})
    TUNING.write_text(tomli_w.dumps(tuning))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
