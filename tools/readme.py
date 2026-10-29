"""README.md, forged from README.source.md (spec 6, item 5).

`scripts/readme_forge.py` is a verbatim lift from marcs-vibe-coding (see REUSE.md) and
is left unmodified. It reads a crude `README.md` beside itself and writes
`README.polished.md` plus Elementor HTML and CSS, none of which belong in this repo. So
the forge is run in a scratch directory on a copy of `README.source.md`, and only the
polished markdown comes back as `README.md`.

  pixi run readme
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from pipeline import common as c

SOURCE = c.ROOT / "README.source.md"
TARGET = c.ROOT / "README.md"
FORGE = c.ROOT / "scripts" / "readme_forge.py"
META = c.ROOT / "readme_meta.json"


def main() -> int:
    if not SOURCE.exists():
        raise SystemExit(f"no {SOURCE.name}: the README is written there, not in README.md")
    # The forge needs `markdown`, which lives in the app venv, not the pipeline env.
    python = c.ROOT / ".venv" / "bin" / "python"
    if not python.exists():
        python = Path(sys.executable)

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        shutil.copy(SOURCE, work / "README.md")
        shutil.copy(META, work / META.name)
        proc = subprocess.run([str(python), str(FORGE), "README.md"], cwd=work,
                              capture_output=True, text=True)
        if proc.returncode != 0:
            raise SystemExit(f"readme_forge failed: {proc.stdout}{proc.stderr}")
        polished = work / "README.polished.md"
        if not polished.exists():
            raise SystemExit(f"readme_forge wrote no polished file: {proc.stdout}")
        TARGET.write_text(polished.read_text())

    placeholders = TARGET.read_text().count("<!-- TODO")
    c.log(f"readme: wrote README.md, {len(TARGET.read_text().splitlines())} lines"
          + (f", {placeholders} placeholders left" if placeholders else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
