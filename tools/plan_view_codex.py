#!/usr/bin/env python3
"""Codex adapter for tools/plan_view.py: prompt on stdin, JPEG to argv[1], identity on stdout.

    plan_view_command: ["python3", "<orchestration>/tools/plan_view_codex.py"]

Runs ``codex exec`` in a read-only, ephemeral session, picks the PNG it added
under $CODEX_HOME/generated_images (default ~/.codex/generated_images), and
converts it to a 1280px JPEG (sips on macOS, Pillow otherwise).  The last
stdout line is ``{"adapter": "codex", "tool": "Codex", "version": ...}``.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


INSTRUCTION = "Use your image generation tool to create exactly one image, then reply only with the word DONE.\n"
WIDTH = 1280


def images_root() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "generated_images"


def _pngs(root: Path) -> set[Path]:
    return set(root.rglob("*.png")) if root.is_dir() else set()


def to_jpeg(source: Path, output: Path) -> None:
    if shutil.which("sips"):
        subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "82", "--resampleWidth", str(WIDTH),
                        str(source), "--out", str(output)], check=True, capture_output=True, timeout=120)
        return
    from PIL import Image  # optional outside macOS
    with Image.open(source) as image:
        image = image.convert("RGB")
        if image.width > WIDTH:
            image = image.resize((WIDTH, round(image.height * WIDTH / image.width)))
        image.save(output, "JPEG", quality=82)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--timeout", type=int, default=1500)
    args = parser.parse_args(argv)
    prompt = sys.stdin.read()
    root = images_root()
    before = _pngs(root)
    version = subprocess.run([args.codex, "--version"], capture_output=True, text=True, timeout=60).stdout.strip()
    with tempfile.TemporaryDirectory(prefix="plan-view-codex-") as scratch:
        run = subprocess.run([args.codex, "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "-"],
                             input=INSTRUCTION + prompt, capture_output=True, text=True, timeout=args.timeout,
                             cwd=scratch)
    time.sleep(2)
    new = sorted(_pngs(root) - before, key=lambda path: path.stat().st_mtime)
    if not new:
        print(f"no image was generated (codex exit {run.returncode})", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    to_jpeg(new[-1], args.output)
    print(json.dumps({"adapter": "codex", "tool": "Codex", "version": version}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
