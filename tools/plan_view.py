#!/usr/bin/env python3
"""Attach one plan-specific installation view to a projected Project record.

Production's visual package draws the same template for every plan, so a reader
of the public record cannot see the work.  After tools/run.py has projected a
canonical plan and the Project's catalog is valid, this step asks an explicitly
configured image generator for one installation view and attaches it as
README-only supplemental media (project-supplemental-public-media/v1).

The prompt is deterministic code over the public plan.md: the encounter (§1),
the concept's mechanism (§4) and the method specifications (§8).  The generator
only draws.  Its contract is provider-neutral:

    <command...> <output.jpg>      prompt on stdin, JPEG written to the path, exit 0

and its last stdout line is a JSON object naming itself:
``{"adapter": "codex", "tool": "Codex", "version": "codex-cli 0.164.0"}``.
tools/plan_view_codex.py is the Codex adapter.

plan.md and the Production attestation are never touched.  The README block,
the manifest and the rebound ``introduction_sha256`` (metadata.yaml and
plans/index.yaml) are the only record changes; the full prompt and output hash
stay in the private run report.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Any, Callable, Mapping

import yaml

from tools.process_policy import child_environment


CONTRACT_VERSION = "project-supplemental-public-media/v1"
MANIFEST = "supplemental-media.json"
VIEW_PATH = "media/prototype-whole.jpg"
BLOCK_START = "<!-- prototype-visualization:start -->"
BLOCK_END = "<!-- prototype-visualization:end -->"
README_ANCHOR = "## 制作入口"
DEFAULT_TIMEOUT_SECONDS = 1800
ADAPTER = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._+()/-]{0,63}")
RECORD_PATH = re.compile(r"plans/P[0-9]{4}-[a-z0-9]+(?:-[a-z0-9]+)*")
RECORD_ID = re.compile(r"P[0-9]{4}")
DISCLAIMER = ("寸法は正確ではなく、制作した現物の写真ではありません。"
              "物理試作、外部検証、展示の実施記録を示しません。")
IMAGE_INSTRUCTION = (
    "A photorealistic wide view (16:9) of a contemporary art installation as it would look when installed, "
    "following these plan facts exactly (sizes, materials, placement, where the viewer stands, and what the "
    "mechanism says the viewer sees or handles). Show every physical element the facts name, including sheets, "
    "marks and colours. Show one or two viewers at true human scale for size reference. Neutral gallery light. "
    "No readable text, no captions, no logos, no watermark."
)


class PlanViewError(ValueError):
    """A fixed, path-free reason why the view was not attached."""


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- prompt -----------------------------------------------------------------

def _section(plan: str, number: str) -> str:
    start = re.search(rf"^## {re.escape(number)}\. .*$", plan, re.MULTILINE)
    if start is None:
        return ""
    end = re.search(r"^## ", plan[start.end():], re.MULTILINE)
    return plan[start.start():start.end() + end.start()] if end else plan[start.start():]


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _row(text: str, label: str) -> str:
    for line in text.splitlines():
        cells = _cells(line)
        if len(cells) >= 2 and cells[0] == label:
            return cells[1]
    return ""


def _spec(plan: str, kind: str) -> str:
    for line in _section(plan, "8").splitlines():
        cells = _cells(line)
        if len(cells) >= 3 and cells[1] == kind:
            match = re.search(r"statement=(.*?)(?:, quantity=|$)", cells[2])
            return match.group(1) if match else cells[2]
    return ""


def plan_facts(plan: str) -> dict[str, str]:
    """Read the facts the view must show from the canonical plan's fixed sections."""
    research = _section(plan, "5")
    encounter = _section(plan, "1")
    facts = {
        "作品": _row(research, "仕様タイトル") or _row(research, "仮説タイトル"),
        "鑑賞者の位置": _row(encounter, "position"),
        "最初の数秒に見えるもの": _row(encounter, "first_seconds"),
        "仕組み": _row(_section(plan, "4"), "mechanism"),
        "寸法": _spec(plan, "method-dimensions-1"),
        "素材": _spec(plan, "method-materials"),
        "組み立て": _spec(plan, "method-assembly"),
        "設置": _spec(plan, "method-installation"),
    }
    return {key: value for key, value in facts.items() if value}


def build_prompt(plan: str) -> str:
    facts = plan_facts(plan)
    if not set(facts) - {"作品"}:
        raise PlanViewError("PLAN_FACTS_MISSING")
    return IMAGE_INSTRUCTION + "\n" + "\n".join(f"- {key}: {value}" for key, value in facts.items()) + "\n"


# --- record -----------------------------------------------------------------

def _regular(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise PlanViewError("RECORD_FILE_UNSAFE")
    return path.read_bytes()


def _safe_media(path: object) -> str:
    if (not isinstance(path, str) or not re.fullmatch(r"media/[A-Za-z0-9._/-]+", path)
            or any(part in {".", ".."} for part in path.split("/")) or str(PurePosixPath(path)) != path):
        raise PlanViewError("SUPPLEMENTAL_MEDIA_INVALID")
    return path


def supplemental_files(target: Path, record_path: str, record_id: str | None = None) -> dict[str, bytes]:
    """Return the target-relative files of a record's verified supplemental media.

    The canonical projection calls this so that a resumed run accepts the view
    this module attached (and removes it when a new plan revision replaces the
    README it was linked from).  An absent manifest is ``{}``; a manifest whose
    bytes, identity or asset hashes do not match raises.
    """
    directory = target / record_path
    manifest_path = directory / MANIFEST
    if not manifest_path.exists() and not manifest_path.is_symlink():
        return {}
    raw = _regular(manifest_path)
    try:
        manifest = json.loads(raw)
    except ValueError as exc:
        raise PlanViewError("SUPPLEMENTAL_MEDIA_INVALID") from exc
    if (not isinstance(manifest, dict) or raw != _canonical(manifest) + b"\n"
            or manifest.get("contract_version") != CONTRACT_VERSION
            or (record_id is not None and manifest.get("record_id") != record_id)
            or not isinstance(manifest.get("assets"), list) or not manifest["assets"]):
        raise PlanViewError("SUPPLEMENTAL_MEDIA_INVALID")
    files = {f"{record_path}/{MANIFEST}": raw}
    for asset in manifest["assets"]:
        if not isinstance(asset, dict):
            raise PlanViewError("SUPPLEMENTAL_MEDIA_INVALID")
        relative = _safe_media(asset.get("path"))
        data = _regular(directory / relative)
        if asset.get("sha256") != "sha256:" + _sha256(data):
            raise PlanViewError("SUPPLEMENTAL_MEDIA_CHANGED")
        files[f"{record_path}/{relative}"] = data
    return files


def _record(target: Path, record_id: str) -> tuple[str, dict[str, Any]]:
    index = yaml.safe_load(_regular(target / "plans/index.yaml").decode("utf-8"))
    rows = [row for row in (index or {}).get("records", []) if isinstance(row, dict) and row.get("id") == record_id]
    if len(rows) != 1 or not isinstance(rows[0].get("path"), str) or not RECORD_PATH.fullmatch(rows[0]["path"]):
        raise PlanViewError("RECORD_NOT_INDEXED")
    directory = target / rows[0]["path"]
    if directory.is_symlink() or not directory.is_dir():
        raise PlanViewError("RECORD_DIRECTORY_UNSAFE")
    return rows[0]["path"], rows[0]


def already_present(directory: Path) -> bool:
    if (directory / MANIFEST).exists():
        return True
    readme = directory / "README.md"
    return readme.is_file() and BLOCK_START in readme.read_text(encoding="utf-8")


def _media_policy(target: Path) -> tuple[int, set[str]]:
    layout = yaml.safe_load(_regular(target / "public-project.yaml").decode("utf-8"))
    policy = layout.get("media_policy") if isinstance(layout, dict) else None
    if not isinstance(policy, dict) or not isinstance(policy.get("max_file_bytes"), int):
        raise PlanViewError("RECEIVER_MEDIA_POLICY_MISSING")
    return policy["max_file_bytes"], set(policy.get("allowed_extensions") or [])


def _head(target: Path) -> str:
    completed = subprocess.run(["git", "-C", str(target), "rev-parse", "HEAD"], capture_output=True, text=True,
                               timeout=60, env=child_environment())
    commit = completed.stdout.strip()
    if completed.returncode or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise PlanViewError("TARGET_HEAD_MISSING")
    return commit


# --- generation -------------------------------------------------------------

def _identity(stdout: str) -> dict[str, str]:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    try:
        value = json.loads(lines[-1]) if lines else None
    except ValueError:
        value = None
    if not isinstance(value, dict):
        raise PlanViewError("GENERATOR_IDENTITY_MISSING")
    adapter, tool, version = value.get("adapter"), value.get("tool"), value.get("version", "")
    if (not isinstance(adapter, str) or not ADAPTER.fullmatch(adapter) or len(adapter) > 32
            or not isinstance(tool, str) or not LABEL.fullmatch(tool)
            or not isinstance(version, str) or (version and not LABEL.fullmatch(version))):
        raise PlanViewError("GENERATOR_IDENTITY_INVALID")
    return {"adapter": adapter, "tool": tool, "version": version}


def generate(command: list[str], prompt: str, output: Path, *, timeout: int) -> dict[str, str]:
    """Run the configured generator without write credentials and check what it wrote."""
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or output.is_symlink():
        output.unlink()
    try:
        completed = subprocess.run([*command, str(output)], input=prompt, capture_output=True, text=True,
                                   timeout=timeout, cwd=output.parent, env=child_environment())
    except subprocess.TimeoutExpired as exc:
        raise PlanViewError("GENERATOR_TIMEOUT") from exc
    except OSError as exc:
        raise PlanViewError("GENERATOR_NOT_RUNNABLE") from exc
    if completed.returncode:
        error = PlanViewError("GENERATOR_FAILED")
        error.detail = (completed.stderr or "").strip().splitlines()[-5:]
        raise error
    identity = _identity(completed.stdout)
    if output.is_symlink() or not output.is_file():
        raise PlanViewError("GENERATOR_WROTE_NO_IMAGE")
    data = output.read_bytes()
    if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
        raise PlanViewError("GENERATOR_IMAGE_NOT_JPEG")
    return identity


# --- attachment -------------------------------------------------------------

def readme_block(*, title: str, identity: Mapping[str, str], generated_at: str, prompt_sha256: str) -> str:
    alt = re.sub(r"[\[\]\r\n]+", " ", title).strip()
    made = generated_at[:10]
    if identity.get("version"):
        made += f"、{identity['version']}"
    return (
        f"{BLOCK_START}\n## 試作の可視化\n\n"
        f"![{alt} — 設置の想定図]({VIEW_PATH})\n\n"
        "公開済みの `plan.md` の完成像（§1）、コンセプトの仕組み（§4）、技術仕様の寸法・素材・組み立て・設置（§8）から、"
        "決まった手順で組み立てた指示で描いた設置の想定図です。"
        f"{identity['tool']} の画像生成で作りました（{made}、指示文 sha256 `{prompt_sha256[:12]}`）。"
        f"{DISCLAIMER}\n"
        f"{BLOCK_END}\n\n"
    )


def _rebind(text: str, old: str, new: str, prefix: str) -> str:
    line = f'{prefix}"introduction_sha256": "{old}"'
    if text.count(line) != 1:
        raise PlanViewError("INTRODUCTION_HASH_NOT_BOUND")
    return text.replace(line, f'{prefix}"introduction_sha256": "{new}"')


def attach(target: Path, record_path: str, record_id: str, *, image: bytes, identity: Mapping[str, str],
           generated_at: str, prompt_sha256: str, source_commit: str, title: str) -> dict[Path, bytes | None]:
    """Write the view, manifest, README block and rebound hashes; return the prior bytes for rollback."""
    directory = target / record_path
    readme_path, metadata_path, index_path = directory / "README.md", directory / "metadata.yaml", target / "plans/index.yaml"
    view, manifest_path = directory / VIEW_PATH, directory / MANIFEST
    if view.exists() or view.is_symlink() or manifest_path.exists() or manifest_path.is_symlink():
        raise PlanViewError("VIEW_PATH_OCCUPIED")
    readme_bytes = _regular(readme_path)
    readme = readme_bytes.decode("utf-8")
    metadata_text, index_text = _regular(metadata_path).decode("utf-8"), _regular(index_path).decode("utf-8")
    old_hash = (yaml.safe_load(metadata_text) or {}).get("introduction_sha256")
    if old_hash != _sha256(readme_bytes):
        raise PlanViewError("INTRODUCTION_MISMATCH")
    if readme.count(README_ANCHOR) != 1:
        raise PlanViewError("README_ANCHOR_MISSING")
    from tools.security import scan_public_projection
    block = readme_block(title=title, identity=identity, generated_at=generated_at, prompt_sha256=prompt_sha256)
    if scan_public_projection(block, f"{record_path}/README.md"):
        raise PlanViewError("README_BLOCK_FAILED_PUBLIC_POLICY")
    new_readme = readme.replace(README_ANCHOR, block + README_ANCHOR).encode("utf-8")
    new_hash = _sha256(new_readme)
    manifest = {
        "assets": [{"byte_length": len(image), "media_type": "image/jpeg", "path": VIEW_PATH,
                    "purpose": "README_DOCUMENTATION",
                    "rights_ref": f"{identity['adapter']}-image-generation/{record_id}/plan-view/v1",
                    "rights_status": "PUBLIC_CLEARED", "sha256": "sha256:" + _sha256(image)}],
        "contract_version": CONTRACT_VERSION, "record_id": record_id,
        "source": {"basis": "existing-public-record", "commit": source_commit, "locator": record_path,
                   "repository": "agentic-art-project"},
    }
    writes = {
        view: image,
        manifest_path: _canonical(manifest) + b"\n",
        readme_path: new_readme,
        metadata_path: _rebind(metadata_text, old_hash, new_hash, "").encode("utf-8"),
        index_path: _rebind(index_text, old_hash, new_hash, "  ").encode("utf-8"),
    }
    prior: dict[Path, bytes | None] = {path: (None if path in {view, manifest_path} else path.read_bytes()) for path in writes}
    try:
        for path, data in writes.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    except OSError:
        restore(prior)
        raise
    return prior


def restore(prior: Mapping[Path, bytes | None]) -> None:
    for path, data in prior.items():
        if data is None:
            if path.exists() or path.is_symlink():
                path.unlink()
        else:
            path.write_bytes(data)
    for path in prior:
        if path.parent.name == "media" and path.parent.is_dir() and not any(path.parent.iterdir()):
            path.parent.rmdir()


# --- run step ---------------------------------------------------------------

def run_step(target: Path, public_ids: list[str], *, command: list[str] | None, python: str, work: Path,
             sync: Callable[[Path, str], Mapping[str, Any]], timeout: int = DEFAULT_TIMEOUT_SECONDS,
             now: Callable[[], datetime] | None = None) -> dict[str, Any]:
    """Create and attach one installation view for the projected record; never raise.

    SKIPPED when no generator is configured, ALREADY_PRESENT when the record
    already carries supplemental media, ATTACHED after the Project's catalog
    sync and validator pass again, FAILED (with the target restored) otherwise.
    """
    if not command:
        return {"status": "SKIPPED", "reason": "NOT_CONFIGURED"}
    if len(public_ids) != 1 or not isinstance(public_ids[0], str) or not RECORD_ID.fullmatch(public_ids[0]):
        return {"status": "SKIPPED", "reason": "NOT_ONE_PROJECTED_RECORD"}
    record_id = public_ids[0]
    result: dict[str, Any] = {"record_id": record_id}
    prior: dict[Path, bytes | None] | None = None
    try:
        record_path, entry = _record(target, record_id)
        result["record_path"] = record_path
        directory = target / record_path
        if already_present(directory):
            return dict(result, status="ALREADY_PRESENT")
        plan = _regular(directory / "plan.md")
        prompt = build_prompt(plan.decode("utf-8"))
        prompt_sha256 = _sha256(prompt.encode("utf-8"))
        result.update(prompt=prompt, prompt_sha256=prompt_sha256, plan_sha256=_sha256(plan))
        max_bytes, extensions = _media_policy(target)
        if ".jpg" not in extensions:
            raise PlanViewError("RECEIVER_REJECTS_JPEG")
        source_commit = _head(target)
        generated_at = (now or (lambda: datetime.now(timezone.utc)))().isoformat(timespec="seconds")
        output = work / "plan-view" / f"{record_id}.jpg"
        identity = generate(list(command), prompt, output, timeout=timeout)
        image = output.read_bytes()
        if len(image) > max_bytes:
            raise PlanViewError("RECEIVER_MEDIA_LIMIT")
        result.update(generator=identity, generated_at=generated_at, output_sha256=_sha256(image),
                      byte_length=len(image), source_commit=source_commit,
                      rights_ref=f"{identity['adapter']}-image-generation/{record_id}/plan-view/v1")
        prior = attach(target, record_path, record_id, image=image, identity=identity, generated_at=generated_at,
                       prompt_sha256=prompt_sha256, source_commit=source_commit, title=str(entry.get("title", "")))
        synced = dict(sync(target, python))
        result["catalog_sync"] = synced
        if synced.get("status") != "PASSED":
            raise PlanViewError("CATALOG_SYNC_FAILED")
        return dict(result, status="ATTACHED", path=f"{record_path}/{VIEW_PATH}")
    except (PlanViewError, OSError, UnicodeError, ValueError, TypeError, KeyError, yaml.YAMLError,
            subprocess.SubprocessError) as exc:
        reason = str(exc) if isinstance(exc, PlanViewError) else type(exc).__name__
        result.update(status="FAILED", reason=reason)
        if getattr(exc, "detail", None):
            result["detail"] = exc.detail
        if prior is not None:
            try:
                restore(prior)
                result["restored"] = True
                result["catalog_resync"] = dict(sync(target, python))
            except (OSError, subprocess.SubprocessError) as restore_exc:
                result["restored"] = False
                result["restore_error"] = type(restore_exc).__name__
        return result
