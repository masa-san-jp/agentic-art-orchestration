#!/usr/bin/env python3
"""Codex adapter for tools/plan_view.py: prompt on stdin, JPEG to argv[1], identity on stdout.

    --plan-view-command "python3 <orchestration>/tools/plan_view_codex.py"

Runs ``codex exec --json`` in a read-only, ephemeral session and takes the
thread id from its ``thread.started`` event.  Codex writes the images of that
thread under ``$CODEX_HOME/generated_images/<thread id>/`` (default
``~/.codex``).  Exactly one new PNG in that thread's directory is accepted:
an image of any other session, including a concurrent Codex lane working on
private material, is never picked up.  Codex must exit 0.  The PNG becomes a
1280px JPEG (sips on macOS, Pillow otherwise) and the last stdout line is
``{"adapter": "codex", "tool": "Codex", "version": ...}``.

codex runs in its own process group.  The adapter's --timeout (default 1500 s)
is below tools/plan_view.py's outer limit (default 1800 s); on its own timeout,
or on SIGTERM from the outer limit, the adapter stops the whole codex group.

Codex authenticates from its own home.  tools/credential_free.py replaces HOME
with an empty directory, so under that entry this adapter has no Codex login
and fails (GENERATOR_FAILED); there is no sanctioned way to bring model auth
into that entry, and this adapter does not create one.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile


INSTRUCTION = "Use your image generation tool to create exactly one image, then reply only with the word DONE.\n"
WIDTH = 1280
THREAD_ID = re.compile(r"[0-9A-Za-z][0-9A-Za-z-]{7,63}")


class AdapterError(RuntimeError):
    pass


def images_root() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "generated_images"


def thread_id(events: str) -> str:
    """The thread id of this exec, from its first ``thread.started`` JSONL event."""
    for line in events.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "thread.started":
            value = event.get("thread_id")
            if isinstance(value, str) and THREAD_ID.fullmatch(value):
                return value
            break
    raise AdapterError("codex did not report its thread id")


def thread_image(root: Path, thread: str, before: set[Path]) -> Path:
    """Exactly one new PNG in this thread's own directory."""
    directory = root / thread
    if directory.is_symlink() or not directory.is_dir() or directory.resolve().parent != root.resolve():
        raise AdapterError("codex wrote no image for this thread")
    candidates = sorted(path for path in directory.rglob("*.png") if path not in before and path.is_file()
                        and not path.is_symlink())
    if len(candidates) != 1:
        raise AdapterError(f"expected exactly one new image for this thread, found {len(candidates)}")
    return candidates[0]


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


def _stop(process: subprocess.Popen[str]) -> None:
    for signum, wait in ((signal.SIGTERM, 10), (signal.SIGKILL, 5)):
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            continue


def run_codex(codex: str, prompt: str, timeout: int) -> tuple[int, str, str]:
    with tempfile.TemporaryDirectory(prefix="plan-view-codex-") as scratch:
        process = subprocess.Popen([codex, "exec", "--json", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "-"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   cwd=scratch, start_new_session=True)
        previous = signal.signal(signal.SIGTERM, lambda signum, frame: (_stop(process), sys.exit(143)))
        try:
            stdout, stderr = process.communicate(INSTRUCTION + prompt, timeout=timeout)
        except subprocess.TimeoutExpired:
            _stop(process)
            raise AdapterError(f"codex did not finish within {timeout} seconds") from None
        finally:
            signal.signal(signal.SIGTERM, previous)
        return process.returncode, stdout, stderr


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--timeout", type=int, default=1500)
    args = parser.parse_args(argv)
    prompt = sys.stdin.read()
    root = images_root()
    try:
        before = set(root.rglob("*.png")) if root.is_dir() else set()
        version = subprocess.run([args.codex, "--version"], capture_output=True, text=True, timeout=60).stdout.strip()
        returncode, stdout, stderr = run_codex(args.codex, prompt, args.timeout)
        if returncode:
            raise AdapterError(f"codex exited {returncode}: " + " ".join(stderr.strip().splitlines()[-3:])[:400])
        source = thread_image(root, thread_id(stdout), before)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        to_jpeg(source, args.output)
    except (AdapterError, OSError, subprocess.SubprocessError) as exc:
        print(f"plan_view_codex: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"adapter": "codex", "tool": "Codex", "version": version.splitlines()[0] if version else ""},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
