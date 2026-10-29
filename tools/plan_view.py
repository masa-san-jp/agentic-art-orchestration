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
import os
from pathlib import Path, PurePosixPath
import re
import signal
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
BLOCK_PATTERN = re.compile(re.escape(BLOCK_START) + r"\n.*?" + re.escape(BLOCK_END) + r"\n\n", re.DOTALL)
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


def _write(path: Path, data: bytes) -> None:
    """Replace one file atomically so a killed process leaves the old or the new bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.plan-view.tmp")
    with temporary.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _remove(path: Path) -> None:
    if path.exists() or path.is_symlink():
        path.unlink()
    media = path.parent
    if media.name == "media" and media.is_dir() and not any(media.iterdir()):
        media.rmdir()


def _safe_media(path: object) -> str:
    if (not isinstance(path, str) or not re.fullmatch(r"media/[A-Za-z0-9._/-]+", path)
            or any(part in {".", ".."} for part in path.split("/")) or str(PurePosixPath(path)) != path):
        raise PlanViewError("SUPPLEMENTAL_MEDIA_INVALID")
    return path


def generated_rights_ref(record_id: str) -> re.Pattern[str]:
    """rights_ref of a view this tool produced; any other supplemental asset is curated."""
    return re.compile(rf"[a-z0-9]+(?:-[a-z0-9]+)*-image-generation/{re.escape(record_id)}/plan-view/v1")


def _manifest(directory: Path, record_id: str | None) -> tuple[bytes, dict[str, Any]] | None:
    path = directory / MANIFEST
    if not path.exists() and not path.is_symlink():
        return None
    raw = _regular(path)
    try:
        manifest = json.loads(raw)
    except ValueError as exc:
        raise PlanViewError("SUPPLEMENTAL_MEDIA_INVALID") from exc
    if (not isinstance(manifest, dict) or raw != _canonical(manifest) + b"\n"
            or manifest.get("contract_version") != CONTRACT_VERSION
            or (record_id is not None and manifest.get("record_id") != record_id)
            or not isinstance(manifest.get("assets"), list) or not manifest["assets"]
            or not all(isinstance(asset, dict) for asset in manifest["assets"])):
        raise PlanViewError("SUPPLEMENTAL_MEDIA_INVALID")
    return raw, manifest


def supplemental_files(target: Path, record_path: str, record_id: str | None = None) -> dict[str, bytes]:
    """Return the target-relative files of a record's verified supplemental media.

    The canonical projection calls this so that a resumed run accepts the view
    this module attached.  An absent manifest is ``{}``; a manifest whose bytes,
    identity or asset hashes do not match raises.
    """
    directory = target / record_path
    found = _manifest(directory, record_id)
    if found is None:
        return {}
    raw, manifest = found
    files = {f"{record_path}/{MANIFEST}": raw}
    for asset in manifest["assets"]:
        relative = _safe_media(asset.get("path"))
        data = _regular(directory / relative)
        if asset.get("sha256") != "sha256:" + _sha256(data):
            raise PlanViewError("SUPPLEMENTAL_MEDIA_CHANGED")
        files[f"{record_path}/{relative}"] = data
    return files


def generated_view_files(target: Path, record_path: str, record_id: str) -> dict[str, bytes]:
    """The supplemental files a new plan revision may drop: only views this tool generated.

    Raises CURATED_SUPPLEMENTAL_MEDIA when the manifest lists any other asset,
    so curated media from an earlier process is migrated explicitly, never
    deleted silently.
    """
    files = supplemental_files(target, record_path, record_id)
    if not files:
        return {}
    _raw, manifest = _manifest(target / record_path, record_id)  # type: ignore[misc]
    ours = generated_rights_ref(record_id)
    if not all(isinstance(asset.get("rights_ref"), str) and ours.fullmatch(asset["rights_ref"])
               for asset in manifest["assets"]):
        raise PlanViewError("CURATED_SUPPLEMENTAL_MEDIA")
    return files


def strip_block(readme: str) -> str:
    """The README without this tool's block (the exact inverse of the insertion)."""
    return BLOCK_PATTERN.sub("", readme, count=1)


def _index(target: Path) -> dict[str, Any]:
    index = yaml.safe_load(_regular(target / "plans/index.yaml").decode("utf-8"))
    if not isinstance(index, dict) or not isinstance(index.get("records"), list):
        raise PlanViewError("RECEIVER_INDEX_INVALID")
    return index


def _record(target: Path, record_id: str) -> tuple[str, dict[str, Any]]:
    rows = [row for row in _index(target)["records"] if isinstance(row, dict) and row.get("id") == record_id]
    if len(rows) != 1 or not isinstance(rows[0].get("path"), str) or not RECORD_PATH.fullmatch(rows[0]["path"]):
        raise PlanViewError("RECORD_NOT_INDEXED")
    directory = target / rows[0]["path"]
    if directory.is_symlink() or not directory.is_dir():
        raise PlanViewError("RECORD_DIRECTORY_UNSAFE")
    return rows[0]["path"], rows[0]


def _metadata_hash(directory: Path) -> object:
    metadata = yaml.safe_load(_regular(directory / "metadata.yaml").decode("utf-8"))
    return metadata.get("introduction_sha256") if isinstance(metadata, dict) else None


def view_state(target: Path, record_path: str, record_id: str, entry: Mapping[str, Any]) -> str:
    """PRESENT, ABSENT or PARTIAL.

    PRESENT needs the whole receiver contract: a valid manifest whose assets
    match, every asset linked from the README, and the README hash bound in
    both metadata.yaml and plans/index.yaml.  ABSENT needs no manifest, no
    view file, no block and a bound README.  Anything else (an interrupted
    attachment, or a later edit) is PARTIAL.
    """
    directory = target / record_path
    readme_bytes = _regular(directory / "README.md")
    readme = readme_bytes.decode("utf-8")
    bound = _sha256(readme_bytes) == _metadata_hash(directory) == entry.get("introduction_sha256")
    try:
        files = supplemental_files(target, record_path, record_id)
    except PlanViewError:
        return "PARTIAL"
    if files:
        linked = all(f"]({name[len(record_path) + 1:]})" in readme
                     for name in files if not name.endswith("/" + MANIFEST))
        return "PRESENT" if linked and bound else "PARTIAL"
    stray_view = (directory / VIEW_PATH).exists() and VIEW_PATH not in _owner_media(directory)
    absent = not stray_view and BLOCK_START not in readme and BLOCK_END not in readme
    return "ABSENT" if absent and bound else "PARTIAL"


def _rebind_text(text: str, new: str, prefix: str, allowed: set[str]) -> str:
    pattern = re.compile(rf'^{re.escape(prefix)}"introduction_sha256": "([0-9a-f]{{64}})"$', re.MULTILINE)
    matches = [match for match in pattern.finditer(text) if match.group(1) in allowed]
    if len(matches) != 1:
        raise PlanViewError("INTRODUCTION_HASH_NOT_BOUND")
    match = matches[0]
    return text[:match.start(1)] + new + text[match.end(1):]


def remove_view(target: Path, record_path: str, record_id: str) -> None:
    """Put a record whose own generated view is partial or unwanted back to its projected state.

    Only a view this tool generated is removed (manifest absent or every asset
    carrying its rights_ref); curated media raises.  The introduction hash is
    rebound only from a value this tool could have written.
    """
    directory = target / record_path
    found = _manifest(directory, record_id)
    ours = generated_rights_ref(record_id)
    assets = []
    if found is not None:
        if not all(isinstance(a.get("rights_ref"), str) and ours.fullmatch(a["rights_ref"]) for a in found[1]["assets"]):
            raise PlanViewError("CURATED_SUPPLEMENTAL_MEDIA")
        assets = [_safe_media(asset.get("path")) for asset in found[1]["assets"]]
    owner_paths = _owner_media(directory)
    readme_bytes = _regular(directory / "README.md")
    readme = readme_bytes.decode("utf-8")
    stripped = strip_block(readme)
    if BLOCK_START in stripped or BLOCK_END in stripped:
        raise PlanViewError("README_BLOCK_UNRECOGNIZED")
    stripped_bytes = stripped.encode("utf-8")
    allowed = {_sha256(readme_bytes), _sha256(stripped_bytes)}
    new = _sha256(stripped_bytes)
    index_path, metadata_path = target / "plans/index.yaml", directory / "metadata.yaml"
    index_text = _rebind_text(_regular(index_path).decode("utf-8"), new, "  ", allowed)
    metadata_text = _rebind_text(_regular(metadata_path).decode("utf-8"), new, "", allowed)
    _write(metadata_path, metadata_text.encode("utf-8"))
    _write(index_path, index_text.encode("utf-8"))
    _write(directory / "README.md", stripped_bytes)
    _remove(directory / MANIFEST)
    for relative in {*assets, VIEW_PATH} - owner_paths:
        _remove(directory / relative)


def _owner_media(directory: Path) -> set[str]:
    try:
        attestation = json.loads(_regular(directory / "public-plan-attestation.json"))
    except ValueError as exc:
        raise PlanViewError("ATTESTATION_UNREADABLE") from exc
    assets = attestation.get("assets", []) if isinstance(attestation, dict) else []
    return {asset["path"][len("03_plan/"):] for asset in assets
            if isinstance(asset, dict) and isinstance(asset.get("path"), str) and asset["path"].startswith("03_plan/media/")}


def repair_partial(target: Path) -> list[dict[str, str]]:
    """Before a projection, undo any interrupted attachment of this tool's view (never raises).

    A run killed between the record writes can leave metadata.yaml and
    plans/index.yaml disagreeing, which the projection would refuse as a
    conflict.  Only records in PARTIAL state whose view is this tool's are
    touched; curated or unrecognised states are reported and left alone.
    """
    results: list[dict[str, str]] = []
    try:
        rows = [row for row in _index(target)["records"] if isinstance(row, dict)]
    except Exception as exc:  # noqa: BLE001 - this is a best-effort pre-projection check
        return [{"status": "SKIPPED", "reason": type(exc).__name__}]
    for row in rows:
        record_id, record_path = row.get("id"), row.get("path")
        if not isinstance(record_id, str) or not isinstance(record_path, str) or not RECORD_PATH.fullmatch(record_path):
            continue
        try:
            if not (target / record_path).is_dir() or view_state(target, record_path, record_id, row) != "PARTIAL":
                continue
            remove_view(target, record_path, record_id)
            results.append({"record_id": record_id, "status": "REPAIRED"})
        except Exception as exc:  # noqa: BLE001
            reason = str(exc) if isinstance(exc, PlanViewError) else type(exc).__name__
            results.append({"record_id": record_id, "status": "LEFT", "reason": reason})
    return results


def _media_policy(target: Path) -> tuple[int, set[str]]:
    layout = yaml.safe_load(_regular(target / "public-project.yaml").decode("utf-8"))
    policy = layout.get("media_policy") if isinstance(layout, dict) else None
    if not isinstance(policy, dict) or not isinstance(policy.get("max_file_bytes"), int):
        raise PlanViewError("RECEIVER_MEDIA_POLICY_MISSING")
    return policy["max_file_bytes"], set(policy.get("allowed_extensions") or [])


def _git(target: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(target), *args], capture_output=True, timeout=60, env=child_environment())


def source_commit(target: Path, record_path: str) -> tuple[str, bool]:
    """The newest commit that holds this record's plan.md as it is now, else HEAD.

    tools/run.py projects into the working tree and does not commit, so on the
    first run no commit contains the record yet; then the target's HEAD (the
    public record the projection was applied to) is used and reported.
    """
    plan = _regular(target / record_path / "plan.md")
    found = _git(target, "log", "-1", "--format=%H", "--", f"{record_path}/plan.md")
    commit = found.stdout.decode().strip()
    if found.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", commit):
        held = _git(target, "show", f"{commit}:{record_path}/plan.md")
        if held.returncode == 0 and held.stdout == plan:
            return commit, True
    head = _git(target, "rev-parse", "HEAD").stdout.decode().strip()
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise PlanViewError("TARGET_HEAD_MISSING")
    return head, False


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


def _stop_group(process: subprocess.Popen[str]) -> None:
    """Stop the generator and everything it started (it runs in its own process group)."""
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


def generate(command: list[str], prompt: str, output: Path, *, timeout: int) -> dict[str, str]:
    """Run the configured generator without write credentials and check what it wrote."""
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or output.is_symlink():
        output.unlink()
    try:
        process = subprocess.Popen([*command, str(output)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, cwd=output.parent, env=child_environment(),
                                   start_new_session=True)
    except OSError as exc:
        raise PlanViewError("GENERATOR_NOT_RUNNABLE") from exc
    try:
        stdout, stderr = process.communicate(prompt, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _stop_group(process)
        process.communicate()
        raise PlanViewError("GENERATOR_TIMEOUT") from exc
    if process.returncode:
        error = PlanViewError("GENERATOR_FAILED")
        error.detail = (stderr or "").strip().splitlines()[-5:]
        raise error
    identity = _identity(stdout)
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


def attach(target: Path, record_path: str, record_id: str, *, image: bytes, identity: Mapping[str, str],
           generated_at: str, prompt_sha256: str, source_commit: str, title: str) -> dict[Path, bytes | None]:
    """Write the view, then the manifest, then README, index and metadata; return the prior bytes.

    Every file is replaced atomically and the README/index/metadata come last,
    so an interrupted attachment is a PARTIAL state that remove_view undoes.
    """
    directory = target / record_path
    readme_path, metadata_path, index_path = directory / "README.md", directory / "metadata.yaml", target / "plans/index.yaml"
    view, manifest_path = directory / VIEW_PATH, directory / MANIFEST
    if view.exists() or view.is_symlink() or manifest_path.exists() or manifest_path.is_symlink():
        raise PlanViewError("VIEW_PATH_OCCUPIED")
    if VIEW_PATH in _owner_media(directory):
        raise PlanViewError("VIEW_PATH_OWNED_BY_PRODUCTION")
    readme_bytes = _regular(readme_path)
    readme = readme_bytes.decode("utf-8")
    old_hash = _sha256(readme_bytes)
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
    writes = [
        (view, image),
        (manifest_path, _canonical(manifest) + b"\n"),
        (readme_path, new_readme),
        (index_path, _rebind_text(_regular(index_path).decode("utf-8"), new_hash, "  ", {old_hash}).encode("utf-8")),
        (metadata_path, _rebind_text(_regular(metadata_path).decode("utf-8"), new_hash, "", {old_hash}).encode("utf-8")),
    ]
    prior: dict[Path, bytes | None] = {path: (None if path in {view, manifest_path} else path.read_bytes())
                                       for path, _data in writes}
    try:
        for path, data in writes:
            _write(path, data)
    except OSError:
        restore(prior)
        raise
    return prior


def restore(prior: Mapping[Path, bytes | None]) -> None:
    """Restore exact prior bytes; metadata, index and README first, the new files last."""
    for path, data in reversed(list(prior.items())):
        if data is None:
            _remove(path)
        else:
            _write(path, data)


# --- run step ---------------------------------------------------------------

def run_step(target: Path, public_ids: list[str], *, command: list[str] | None, python: str, work: Path,
             sync: Callable[[Path, str], Mapping[str, Any]], timeout: int = DEFAULT_TIMEOUT_SECONDS,
             now: Callable[[], datetime] | None = None) -> dict[str, Any]:
    """Create and attach one installation view for the projected record; never raise.

    SKIPPED when no generator is configured, ALREADY_PRESENT when the record
    already carries consistent supplemental media, ATTACHED after the Project's
    catalog sync and validator pass again, FAILED (with the target restored
    where possible) otherwise.  A PARTIAL view of this tool is removed and made
    again; a partial curated state is reported, not touched.
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
        state = view_state(target, record_path, record_id, entry)
        if state == "PRESENT":
            return dict(result, status="ALREADY_PRESENT")
        if state == "PARTIAL":
            remove_view(target, record_path, record_id)
            record_path, entry = _record(target, record_id)
            if view_state(target, record_path, record_id, entry) != "ABSENT":
                raise PlanViewError("PARTIAL_VIEW_NOT_REPAIRED")
            result["repaired_partial_view"] = True
        directory = target / record_path
        plan = _regular(directory / "plan.md")
        prompt = build_prompt(plan.decode("utf-8"))
        prompt_sha256 = _sha256(prompt.encode("utf-8"))
        result.update(prompt=prompt, prompt_sha256=prompt_sha256, plan_sha256=_sha256(plan))
        max_bytes, extensions = _media_policy(target)
        if ".jpg" not in extensions:
            raise PlanViewError("RECEIVER_REJECTS_JPEG")
        commit, contains_record = source_commit(target, record_path)
        generated_at = (now or (lambda: datetime.now(timezone.utc)))().isoformat(timespec="seconds")
        output = work / "plan-view" / f"{record_id}.jpg"
        identity = generate(list(command), prompt, output, timeout=timeout)
        image = output.read_bytes()
        if len(image) > max_bytes:
            raise PlanViewError("RECEIVER_MEDIA_LIMIT")
        result.update(generator=identity, generated_at=generated_at, output=str(output), output_sha256=_sha256(image),
                      byte_length=len(image), source_commit=commit, source_commit_contains_record=contains_record,
                      rights_ref=f"{identity['adapter']}-image-generation/{record_id}/plan-view/v1")
        prior = attach(target, record_path, record_id, image=image, identity=identity, generated_at=generated_at,
                       prompt_sha256=prompt_sha256, source_commit=commit, title=str(entry.get("title", "")))
        synced = dict(sync(target, python))
        result["catalog_sync"] = synced
        if synced.get("status") != "PASSED":
            raise PlanViewError("CATALOG_SYNC_FAILED")
        return dict(result, status="ATTACHED", path=f"{record_path}/{VIEW_PATH}")
    except Exception as exc:  # noqa: BLE001 - an optional step after a successful projection never raises
        reason = str(exc) if isinstance(exc, PlanViewError) else type(exc).__name__
        result.update(status="FAILED", reason=reason)
        if getattr(exc, "detail", None):
            result["detail"] = exc.detail
        if prior is not None:
            try:
                restore(prior)
                resync = dict(sync(target, python))
            except Exception as restore_exc:  # noqa: BLE001
                result.update(restored=False, restore_error=type(restore_exc).__name__)
            else:
                result["catalog_resync"] = resync
                # Restored only when the record bytes are back and the Project validates again.
                result["restored"] = resync.get("status") == "PASSED"
        return result
