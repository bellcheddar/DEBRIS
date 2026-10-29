"""Push the fused model to the Hub and create the ZeroGPU Space (spec 5.6 path A).

Needs HF_TOKEN with write scope. Without one the build logs it and the weekly run
uses path B (the Studio launchd job); this script stays ready for the token.

  pixi run python hf/push_model.py            # model and Space
  pixi run python hf/push_model.py --model-only
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import common as c  # noqa: E402

FUSED = c.ADAPTERS / "debris_v1_fused"
SPACE_DIR = Path(__file__).resolve().parent / "space"


def main() -> int:
    ap = argparse.ArgumentParser(description="Push the DEBRIS tagger to Hugging Face")
    ap.add_argument("--model-only", action="store_true")
    ap.add_argument("--space-only", action="store_true")
    ap.add_argument("--allow-expiring", action="store_true",
                    help="push with a credential that expires, for a one-off test of the Space")
    args = ap.parse_args()

    token = c.api_key("HF_TOKEN")
    cfg = c.load_toml("hf.toml")
    if not token:
        c.log("hf: no HF_TOKEN; model and Space not pushed, weekly inference stays on path B")
        return 1

    # A browser login leaves a credential good for a few days. Pushing with it would work
    # today and strand the droplet's weekly timer next week, silently, because the weekly
    # runner logs a failed stage and carries on (D26).
    expires = c.token_expiry(token)
    if expires and not args.allow_expiring:
        c.log(f"hf: this token expires {expires}, which is too soon for a weekly timer. "
              f"Create one at https://huggingface.co/settings/tokens with write scope, or "
              f"pass --allow-expiring to push with it anyway and stay on path B.")
        return 1

    from huggingface_hub import HfApi

    api = HfApi(token=token)
    model_repo = cfg.get("model_repo", "Dellboy/debris-tagger-v1")
    space_repo = cfg.get("space_repo", "Dellboy/debris-tagger")

    if not args.space_only:
        if not FUSED.exists():
            c.log(f"hf: {FUSED} is absent; train first")
            return 1
        api.create_repo(model_repo, repo_type="model", exist_ok=True,
                        private=bool(cfg.get("private_model", True)))
        card = c.ROOT / "MODEL_CARD.md"
        if card.exists():
            shutil.copy(card, FUSED / "README.md")
        api.upload_folder(folder_path=str(FUSED), repo_id=model_repo, repo_type="model",
                          commit_message="DEBRIS tagger debris_v1 (fused, de-quantised)")
        c.log(f"hf: pushed {model_repo}")

    if not args.model_only:
        # The Space validates against the same vocabulary the tagger was trained on,
        # so schema.py and vocab.toml travel with it.
        shutil.copy(c.ROOT / "pipeline" / "schema.py", SPACE_DIR / "schema.py")
        shutil.copy(c.CONFIG / "vocab.toml", SPACE_DIR / "vocab.toml")
        # schema.py imports pipeline.common for the vocabulary; the Space copy reads
        # the TOML beside it instead.
        text = (SPACE_DIR / "schema.py").read_text().replace(
            "from pipeline import common as c\n\nV = c.vocab()",
            "import tomllib, pathlib\n\n"
            "V = tomllib.loads((pathlib.Path(__file__).parent / 'vocab.toml').read_text())")
        (SPACE_DIR / "schema.py").write_text(text)
        # Hardware is requested at creation; an existing Space keeps whatever it has,
        # so the log below says where to check it.
        try:
            api.create_repo(space_repo, repo_type="space", exist_ok=True, space_sdk="gradio",
                            space_hardware=cfg.get("space_hardware", "zero-a10g"))
        except TypeError:
            api.create_repo(space_repo, repo_type="space", exist_ok=True, space_sdk="gradio")
        api.upload_folder(folder_path=str(SPACE_DIR), repo_id=space_repo, repo_type="space",
                          commit_message="DEBRIS tagger Space (ZeroGPU)")
        api.add_space_secret(repo_id=space_repo, key="HF_TOKEN", value=token)
        c.log(f"hf: pushed Space {space_repo}; set its hardware to "
              f"{cfg.get('space_hardware', 'zero-a10g')} in the Space settings if it is not already")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
