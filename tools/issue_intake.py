#!/usr/bin/env python3
"""Observe open GitHub Issues and report queue/SSOT readiness without writing remotely."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "config/repositories.yaml"
QUEUE_PATH = ROOT / "execution/task-queue.yaml"
SCHEMA_PATH = ROOT / "schemas/issue-intake-report.schema.json"
URL_PATTERN = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/([1-9][0-9]*)$")
FULL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
OBSERVABLE_ACCEPTANCE = re.compile(r"(?im)^\s*#{1,6}\s*(?:受入条件|acceptance|acceptance criteria)\b")
VERIFICATION = re.compile(r"(?im)^\s*#{1,6}\s*(?:検証コマンド|verification commands?|checks?)\b")
HUMAN_GATE = re.compile(r"(?im)^\s*#{1,6}\s*(?:human gate|human approval|人間(?:の)?(?:承認|ゲート))\b")

try:
    from tools.validate import _schema_errors, load_json, load_yaml
except ModuleNotFoundError:  # pragma: no cover - direct CLI fallback
    sys.path.insert(0, str(ROOT))
    from tools.validate import _schema_errors, load_json, load_yaml


class IssueIntakeError(ValueError):
    """The Issue intake input or report cannot be accepted safely."""


def _error(detail: str, remediation: str) -> IssueIntakeError:
    return IssueIntakeError(f"issue intake: {detail}; remediation: {remediation}")


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _timestamp(value: object) -> str:
    if not isinstance(value, str):
        raise _error("source observed_at must be a string", "provide an ISO-8601 timestamp with timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _error("source observed_at is not ISO-8601", "use a timestamp with timezone") from exc
    if parsed.tzinfo is None:
        raise _error("source observed_at lacks timezone", "include Z or an explicit UTC offset")
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _relative_locator(value: str) -> str:
    path = Path(value)
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return f"external/{path.name or 'issue-input.json'}"


def _manifest_repositories() -> dict[str, str]:
    manifest = load_yaml(MANIFEST_PATH)
    repositories = manifest.get("repositories") if isinstance(manifest, Mapping) else None
    result = {
        entry["full_name"]: entry["id"]
        for entry in repositories or []
        if isinstance(entry, Mapping)
        and isinstance(entry.get("id"), str)
        and isinstance(entry.get("full_name"), str)
    }
    result["masa-san-jp/agentic-art-orchestration"] = "agentic-art-orchestration"
    return result


def _queued_issue_urls(queue: Mapping[str, object]) -> set[str]:
    tasks = queue.get("tasks") if isinstance(queue, Mapping) else None
    if not isinstance(tasks, list):
        raise _error("task queue does not contain a task list", "repair execution/task-queue.yaml")
    queued: set[str] = set()
    for index, task in enumerate(tasks):
        if not isinstance(task, Mapping):
            raise _error(f"queue task {index} is not an object", "repair execution/task-queue.yaml")
        issue_url = task.get("issue_ssot")
        if isinstance(issue_url, str) and URL_PATTERN.fullmatch(issue_url):
            queued.add(issue_url)
    return queued


def _acceptance_present(body: str) -> bool:
    if not OBSERVABLE_ACCEPTANCE.search(body):
        return False
    section = body[OBSERVABLE_ACCEPTANCE.search(body).end() :]
    next_heading = re.search(r"(?m)^\s*#{1,6}\s+", section)
    if next_heading:
        section = section[: next_heading.start()]
    return bool(re.search(r"(?m)^\s*(?:[-*]\s+)?(?:\[[ xX]\]\s+\S|[-*]\s+\S)", section))


def _verification_present(body: str) -> bool:
    if not VERIFICATION.search(body):
        return False
    section = body[VERIFICATION.search(body).end() :]
    next_heading = re.search(r"(?m)^\s*#{1,6}\s+", section)
    if next_heading:
        section = section[: next_heading.start()]
    return bool(re.search(r"(?m)^\s*(?:[-*]\s+)?(?:`[^`]+`|~~~|```|\.venv/bin/python|python3\s+-m)\S*", section))


def _human_gate_present(body: str) -> bool:
    return bool(HUMAN_GATE.search(body))


def _issue_metadata(issue: Mapping[str, object], default_repository: str | None, repository_ids: Mapping[str, str]) -> tuple[dict, str]:
    repository = issue.get("repository") or issue.get("repository_full_name") or default_repository
    if not isinstance(repository, str) or not FULL_NAME_PATTERN.fullmatch(repository):
        raise _error("Issue lacks repository metadata", "add repository to the JSON input or pass --repository")
    number = issue.get("number")
    if not isinstance(number, int) or number < 1:
        raise _error("Issue number is invalid", "use the integer number from gh issue list")
    title = issue.get("title")
    if not isinstance(title, str) or not title.strip():
        raise _error(f"Issue {repository}#{number} lacks a title", "retain the GitHub title")
    url = issue.get("url") or issue.get("html_url")
    if not isinstance(url, str):
        url = f"https://github.com/{repository}/issues/{number}"
    match = URL_PATTERN.fullmatch(url)
    if match is None or match.group(1) != repository or int(match.group(2)) != number:
        raise _error(f"Issue {repository}#{number} URL is inconsistent", "retain the canonical GitHub Issue URL")
    if issue.get("state") not in (None, "OPEN", "open"):
        raise _error(f"Issue {url} is not open", "pass only open Issues to intake")
    body = issue.get("body") or ""
    if not isinstance(body, str):
        raise _error(f"Issue {url} body is not text", "pass the metadata and body returned by gh issue list")
    target_known = repository in repository_ids
    checks = {
        "observable_acceptance": _acceptance_present(body),
        "target_repository": target_known,
        "verification_commands": _verification_present(body),
        "human_gate": _human_gate_present(body),
    }
    missing = [key for key, present in checks.items() if not present]
    ssot = {**checks, "qualified": not missing, "missing": missing}
    return {
        "repository": repository,
        "number": number,
        "title": title.strip(),
        "url": url,
        "ssot": ssot,
    }, repository_ids.get(repository, "")


def _load_input(path: Path, kind: str, default_repository: str | None, observed_at: str | None) -> tuple[dict, list[dict]]:
    if str(path) == "-":
        try:
            payload = json.loads(sys.stdin.read())
        except json.JSONDecodeError as exc:
            raise _error("stdin is not valid JSON", "pipe gh issue list JSON or use --fixture") from exc
        locator = "gh issue list"
    else:
        payload = load_json(path)
        locator = _relative_locator(str(path))
    if isinstance(payload, list):
        issues = payload
        source = {
            "kind": kind,
            "locator": locator,
            "observed_at": observed_at,
        }
    elif isinstance(payload, Mapping):
        issues = payload.get("issues")
        source_data = payload.get("source")
        source = dict(source_data) if isinstance(source_data, Mapping) else {
            "kind": kind,
            "locator": locator,
            "observed_at": observed_at,
        }
        default_repository = payload.get("repository") or default_repository
    else:
        raise _error("input must be a JSON list or object with issues", "pass gh issue list JSON or the fixture envelope")
    if not isinstance(issues, list):
        raise _error("input.issues must be a list", "pass open Issue records")
    source["kind"] = kind if kind != "json" or source.get("kind") is None else source.get("kind")
    source["locator"] = source.get("locator") or locator
    source["observed_at"] = source.get("observed_at") or observed_at
    if default_repository:
        source["repository"] = default_repository
    return source, issues


def _live_input(repositories: list[str], observed_at: str) -> tuple[dict, list[dict]]:
    if not repositories:
        raise _error("live mode requires at least one repository", "pass --repository owner/name")
    issues: list[dict] = []
    for repository in sorted(set(repositories)):
        if not FULL_NAME_PATTERN.fullmatch(repository):
            raise _error(f"repository {repository!r} is invalid", "use owner/name")
        # Fetch metadata and bodies separately.  The body field is not available
        # consistently across gh versions/API modes, and every view must retain
        # the repository scope so an Issue number is never resolved in cwd.
        metadata_command = [
            "gh", "issue", "list", "--repo", repository, "--state", "open", "--limit", "1000", "--json", "number,title,url"
        ]
        completed = subprocess.run(metadata_command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise _error(f"gh issue list failed for {repository}", "authenticate gh or use a networkless fixture")
        try:
            metadata_records = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise _error(f"gh returned invalid JSON for {repository}", "inspect gh issue list output") from exc
        if not isinstance(metadata_records, list):
            raise _error(f"gh returned a non-list for {repository}", "use gh issue list JSON output")
        records: list[dict] = []
        for metadata in metadata_records:
            if not isinstance(metadata, Mapping) or not isinstance(metadata.get("number"), int):
                raise _error(f"gh returned an invalid Issue for {repository}", "retain Issue metadata only")
            viewed = subprocess.run(
                ["gh", "issue", "view", str(metadata["number"]), "--repo", repository, "--json", "body"],
                capture_output=True,
                text=True,
                check=False,
            )
            if viewed.returncode != 0:
                raise _error(f"gh issue view failed for {repository}#{metadata['number']}", "use a networkless fixture")
            try:
                body_record = json.loads(viewed.stdout)
            except json.JSONDecodeError as exc:
                raise _error(f"gh returned invalid body JSON for {repository}#{metadata['number']}", "inspect gh issue view output") from exc
            record = dict(metadata)
            record["body"] = body_record.get("body") if isinstance(body_record, Mapping) else None
            records.append(record)
        for issue in records:
            if not isinstance(issue, Mapping):
                raise _error(f"gh returned a non-object Issue for {repository}", "retain Issue metadata only")
            prepared = dict(issue)
            prepared["repository"] = repository
            issues.append(prepared)
    return {"kind": "live", "locator": "gh issue list", "observed_at": observed_at}, issues


def build_report(
    issues: list[Mapping[str, object]],
    source: Mapping[str, object],
    queue_path: Path = QUEUE_PATH,
) -> dict:
    repository_ids = _manifest_repositories()
    queue_bytes = queue_path.read_bytes()
    queue = load_yaml(queue_path)
    queued_urls = _queued_issue_urls(queue)
    source_out = {
        "kind": source.get("kind"),
        "locator": str(source.get("locator")),
        "observed_at": _timestamp(source.get("observed_at")),
    }
    if source_out["kind"] not in {"fixture", "json", "live"}:
        raise _error("source kind is invalid", "use fixture, json, or live")
    records: list[dict] = []
    seen_urls: set[str] = set()
    for index, issue in enumerate(issues):
        if not isinstance(issue, Mapping):
            raise _error(f"issues[{index}] is not an object", "pass metadata returned by gh issue list")
        metadata, _ = _issue_metadata(issue, source.get("repository"), repository_ids)
        url = metadata["url"]
        if url in seen_urls:
            raise _error(f"duplicate Issue {url}", "retain one record per Issue URL")
        seen_urls.add(url)
        queued = url in queued_urls
        qualified = metadata["ssot"]["qualified"]
        recommendation = "ALREADY_QUEUED" if queued else "REGISTER_BACKLOG" if qualified else "UNQUEUED_NEEDS_SSOT"
        records.append({**metadata, "queued": queued, "recommendation": recommendation})
    records.sort(key=lambda item: (item["repository"], item["number"]))
    qualified_unqueued = sum(item["recommendation"] == "REGISTER_BACKLOG" for item in records)
    report = {
        "contract_version": "issue-intake-report/v1",
        "source": source_out,
        "queue": {
            "path": _relative_locator(str(queue_path)),
            "sha256": hashlib.sha256(queue_bytes).hexdigest(),
            "queued_issue_urls": sorted(queued_urls),
        },
        "issues": records,
        "summary": {
            "total": len(records),
            "queued": sum(item["queued"] for item in records),
            "qualified_unqueued": qualified_unqueued,
            "unqueued_needs_ssot": sum(item["recommendation"] == "UNQUEUED_NEEDS_SSOT" for item in records),
        },
    }
    schema = load_json(SCHEMA_PATH)
    errors = _schema_errors(report, schema, "issue-intake-report")
    if errors:
        raise IssueIntakeError("\n".join(errors))
    return report


def _render(report: Mapping[str, object]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _write_output(path: Path, report: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render(report), encoding="utf-8")



AAK_PIN = "b0e7c7f8d0a1f756fa708deef4fb380a62e45e0d"
AAK_SPEC = "docs/20260905-agentic-art-autonomy-and-knowledge-cycle-specification.md"
AAK_PLAN = "docs/20260905-agentic-art-autonomy-and-knowledge-cycle-implementation-plan.md"
AAK_CONTRACT = "config/aak-task-projection.json"


def _aak_section(text: str, heading: str) -> str:
    matches = list(re.finditer(r"(?m)^## " + re.escape(heading) + r"\s*$", text))
    if len(matches) != 1:
        raise IssueIntakeError(f"AAK: missing or duplicate section {heading}")
    tail = text[matches[0].end():]
    return re.split(r"(?m)^## ", tail, maxsplit=1)[0]


def aak_projection(root: Path = ROOT) -> dict:
    """Derive executable references, never domain payloads, from the two SSOTs."""
    spec_bytes = (root / AAK_SPEC).read_bytes()
    plan_bytes = (root / AAK_PLAN).read_bytes()
    spec, plan = spec_bytes.decode('utf-8'), plan_bytes.decode('utf-8')
    index = _aak_section(plan, 'issue-index')
    dag = _aak_section(plan, 'dependency-dag')
    rows = [line.split('|')[1:-1] for line in index.splitlines() if line.startswith('| AAK-')]
    tasks = []
    for cells in rows:
        task_id, owner, issue, title, _ = [cell.strip() for cell in cells]
        anchor = task_id.lower()
        spec_section = _aak_section(spec, anchor)
        plan_section = _aak_section(plan, anchor)
        issue_urls = re.findall(r'https://github\.com/[^)\s]+/issues/\d+', issue)
        if len(issue_urls) != 1 or f'対象: `masa-san-jp/{owner}`' not in spec_section or f'対象: `masa-san-jp/{owner}`' not in plan_section:
            raise IssueIntakeError(f'AAK: owner/issue mismatch for {task_id}')
        issue_url = issue_urls[0]
        if not issue_url.startswith(f'https://github.com/masa-san-jp/{owner}/issues/') or issue_url not in spec_section:
            raise IssueIntakeError(f'AAK: Issue authority mismatch for {task_id}')
        dep_rows = [line for line in dag.splitlines() if line.startswith(f'| [{task_id}]')]
        if len(dep_rows) != 1:
            raise IssueIntakeError(f'AAK: missing/duplicate DAG row {task_id}')
        dep_cells = [x.strip() for x in dep_rows[0].split('|')[1:-1]]
        dependencies = re.findall(r'\[(AAK-\d+)\]', dep_cells[2])
        external = re.findall(r'https://github\.com/[^)\s]+/issues/\d+', dep_cells[3])
        declared = re.search(r'(?m)^前提: (.+)$', plan_section)
        if dep_cells[1] != owner or declared is None or re.findall(r'\[(AAK-\d+)\]', declared[1]) != dependencies or re.findall(r'https://github\.com/[^)\s]+/issues/\d+', declared[1]) != external:
            raise IssueIntakeError(f'AAK: DAG/section mismatch {task_id}')
        checks = re.findall(r'```bash\n(.*?)\n```', plan_section, re.S)
        acceptance = re.findall(re.escape(task_id) + r'-AC\d+', spec_section)
        if len(checks) != 1 or not acceptance or len(acceptance) != len(set(acceptance)):
            raise IssueIntakeError(f'AAK: missing checks/acceptance {task_id}')
        base = f'https://github.com/masa-san-jp/agentic-art-orchestration/blob/{AAK_PIN}/'
        tasks.append({'id':task_id, 'owner':owner, 'issue_ssot':issue_url,
            'title':title, 'depends_on':dependencies, 'external_dependencies':external,
            'specification':base+AAK_SPEC+'#'+anchor, 'implementation_plan':base+AAK_PLAN+'#'+anchor,
            'acceptance_ids':acceptance, 'checks':checks[0].splitlines()})
    ids = [task['id'] for task in tasks]
    if ids != [f'AAK-{i:02}' for i in range(1,14)] or len({task['owner'] for task in tasks}) != 8:
        raise IssueIntakeError('AAK: expected 13 unique ordered tasks over 8 owners')
    by_id = {t['id']:t for t in tasks}
    visited, active = set(), set()
    def visit(task_id):
        if task_id not in by_id or task_id in active:
            raise IssueIntakeError(f'AAK: unknown dependency or cycle {task_id}')
        if task_id in visited:
            return
        active.add(task_id)
        for dependency in by_id[task_id]['depends_on']:
            visit(dependency)
        active.remove(task_id)
        visited.add(task_id)
    for task_id in ids:
        visit(task_id)
    return {'contract_version':'aak-task-projection/v1', 'source_commit':AAK_PIN,
        'source_hashes':{AAK_SPEC:hashlib.sha256(spec_bytes).hexdigest(), AAK_PLAN:hashlib.sha256(plan_bytes).hexdigest()},
        'tasks':tasks}


def aak_dependency_evidence_ready(task: Mapping) -> bool:
    """CLOSED and PR existence are not owner acceptance evidence."""
    evidence = task.get('dependency_evidence', {})
    for url in task.get('external_dependencies', []):
        record = evidence.get(url, {}) if isinstance(evidence, dict) else {}
        if not (isinstance(record, dict) and record.get('status') == 'PASS'
                and re.fullmatch(r'[0-9a-f]{40}', str(record.get('candidate_commit', '')))
                and record.get('contract_version') and record.get('acceptance_evidence')):
            return False
    return True


def validate_aak_projection(root: Path = ROOT, queue: Mapping | None = None) -> list[str]:
    try:
        expected = aak_projection(root)
        actual = json.loads((root / AAK_CONTRACT).read_text(encoding='utf-8'))
        if actual != expected:
            return ['AAK: contract hash/content mismatch; regenerate from reviewed pinned SSOTs']
        queue = queue if queue is not None else load_yaml(root / 'execution/task-queue.yaml')
        selected = [t for t in queue['tasks'] if str(t.get('id','')).startswith('AAK-')]
        if [t['id'] for t in selected] != [t['id'] for t in expected['tasks']]:
            return ['AAK: missing/duplicate/out-of-order queue task']
        errors = []
        contract_hash = hashlib.sha256(_canonical(expected).encode()).hexdigest()
        for actual_task, expected_task in zip(selected, expected['tasks']):
            for field, value in expected_task.items():
                if actual_task.get(field) != value:
                    errors.append(f"AAK: {actual_task['id']}.{field} differs from SSOT projection")
            if actual_task.get('contract_sha256') != contract_hash:
                errors.append(f"AAK: {actual_task['id']} contract hash mismatch")
            if actual_task.get('status') in {'READY','IN_PROGRESS','DONE'} and not aak_dependency_evidence_ready(actual_task):
                errors.append(f"AAK: {actual_task['id']} external dependencies lack owner evidence")
            if actual_task.get('status') == 'DONE':
                evidence = actual_task.get('acceptance_evidence', {})
                for ac in expected_task['acceptance_ids']:
                    result = evidence.get(ac, {}) if isinstance(evidence, dict) else {}
                    if not (isinstance(result, dict) and result.get('status') == 'PASS' and result.get('reference') and re.fullmatch(r'[0-9a-f]{40}', str(result.get('candidate_commit','')))):
                        errors.append(f'AAK: {ac} missing candidate/acceptance evidence')
        return errors
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f'AAK: {exc}']


def register_aak(root: Path = ROOT) -> None:
    """Append once; preserve previous tasks and all execution evidence."""
    import yaml
    projection = aak_projection(root)
    queue_path = root / 'execution/task-queue.yaml'
    queue = load_yaml(queue_path)
    if any(str(t.get('id','')).startswith('AAK-') for t in queue['tasks']):
        errors = validate_aak_projection(root, queue)
        if errors:
            raise IssueIntakeError('; '.join(errors))
        return
    contract_hash = hashlib.sha256(_canonical(projection).encode()).hexdigest()
    additions = []
    for task in projection['tasks']:
        additions.append({**task, 'milestone':'AAK', 'status':'READY' if task['id']=='AAK-01' else 'BACKLOG',
            'acceptance':task['specification'], 'target_repositories':[task['owner']],
            'agent_terminal':'DRAFT_PR_READY', 'contract_sha256':contract_hash,
            'dependency_evidence':{}, 'acceptance_evidence':{}})
    # Preserve the actual queue's sequence indentation and verify the append
    # before replacing either projection file. Legacy records stay byte-identical.
    original = queue_path.read_text(encoding='utf-8')
    match = re.search(r'(?m)^( *)- id:', original)
    if match is None:
        raise IssueIntakeError('AAK: cannot locate the native task sequence')
    indent = match[1]
    addition = yaml.safe_dump(additions, allow_unicode=True, sort_keys=False)
    appended = original + '\n' + ''.join(indent + line + '\n' for line in addition.splitlines())
    parsed = yaml.safe_load(appended)
    if parsed.get('tasks') != queue['tasks'] + additions:
        raise IssueIntakeError('AAK: append changed existing task structure')
    (root / AAK_CONTRACT).write_text(json.dumps(projection,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    queue_path.write_text(appended,encoding='utf-8')


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv == ["--register-aak"]:
        register_aak()
        print("AAK projection registered; no task marked DONE")
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", type=Path, help="networkless issue-intake envelope")
    source.add_argument("--input", type=Path, help="gh issue list JSON or an intake envelope")
    source.add_argument("--live", action="store_true", help="read open Issues through gh without writing")
    parser.add_argument("--repository", action="append", help="owner/name for raw JSON or live mode; repeat for more repositories")
    parser.add_argument("--observed-at", help="fixed observation timestamp for raw JSON or live mode")
    parser.add_argument("--queue", type=Path, default=QUEUE_PATH, help="task queue to compare; defaults to the parent queue")
    parser.add_argument("--output", type=Path, help="optional report output path")
    parser.add_argument("--check", action="store_true", help="prove that repeated report generation is byte-identical")
    args = parser.parse_args(argv)
    try:
        if args.live:
            if not args.observed_at:
                raise _error("live mode requires --observed-at", "supply the fixed read timestamp for a reproducible report")
            source_data, issues = _live_input(args.repository or [], args.observed_at)
        else:
            path = args.fixture or args.input
            source_kind = "fixture" if args.fixture else "json"
            source_data, issues = _load_input(path, source_kind, (args.repository or [None])[0], args.observed_at)
        report = build_report(issues, source_data, args.queue)
        rendered = _render(report)
        if args.check:
            repeated = build_report(copy.deepcopy(issues), dict(source_data), args.queue)
            if rendered != _render(repeated):
                raise _error("repeated report bytes differ", "keep source, queue, and sorting deterministic")
        if args.output:
            _write_output(args.output, report)
        sys.stdout.write(rendered)
        return 0
    except (IssueIntakeError, OSError, KeyError, TypeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
