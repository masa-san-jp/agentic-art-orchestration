"""Verify internal Production completion at the qualified owner boundary."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import yaml


class PlanCompletionError(ValueError):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checked_code(root, commit):
    root = Path(root)
    if not root.is_absolute() or root.resolve() != root or not re.fullmatch(r'[0-9a-f]{40}', str(commit)):
        raise PlanCompletionError('CODE_PIN_REQUIRED')
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args], text=True, stderr=subprocess.DEVNULL).strip()
    if git('rev-parse', '--show-toplevel') != str(root) or git('rev-parse', 'HEAD') != commit or git('status', '--porcelain'):
        raise PlanCompletionError('CODE_PIN_OR_CLEANLINESS_MISMATCH')
    return root


def verify_plan(*, code_root, code_commit, project_root, python=None, expected=None, research_commit=None):
    """No owner schema copy, public approval inference, or worker success shortcut."""
    code = checked_code(code_root, code_commit)
    project = Path(project_root)
    if not project.is_absolute() or project.resolve() != project or project == code or code in project.parents:
        raise PlanCompletionError('EXTERNAL_CANONICAL_PROJECT_REQUIRED')
    command = code / 'tools/plan_actionability.py'
    if not command.is_file() or command.is_symlink():
        raise PlanCompletionError('QUALIFIED_AAK10_OWNER_REQUIRED')
    plan = project / '03_plan/production-plan.md'
    aggregate = plan.with_suffix('.yaml')
    def snapshot():
        paths = [plan, aggregate, project / '02_specification/production-method.yaml']
        handoff_path = project / '00_handoff/production-handoff.yaml'
        if handoff_path.exists():
            paths.append(handoff_path)
        media = project / '03_plan/media'
        if media.is_symlink():
            raise PlanCompletionError('ASSET_SYMLINK')
        if media.exists():
            paths += sorted(media.rglob('*'))
        result = {}
        for path in paths:
            if path.is_symlink() or path.resolve() != path:
                raise PlanCompletionError('CANONICAL_PATH_SYMLINK')
            if path.is_dir():
                continue
            if not path.is_file() or not path.stat().st_size:
                raise PlanCompletionError('CANONICAL_ARTIFACT_MISSING')
            result[str(path.relative_to(project))] = digest(path.read_bytes())
        return result
    if research_commit is not None:
        if not re.fullmatch('[0-9a-f]{40}', str(research_commit)):
            raise PlanCompletionError('RESEARCH_PIN_REQUIRED')
        handoff_path = project / '00_handoff/production-handoff.yaml'
        if not handoff_path.is_file() or handoff_path.resolve() != handoff_path:
            raise PlanCompletionError('PINNED_HANDOFF_REQUIRED')
        handoff = yaml.safe_load(handoff_path.read_bytes())
        if not isinstance(handoff, dict) or handoff.get('research_commit') != research_commit:
            raise PlanCompletionError('RESEARCH_HANDOFF_PIN_MISMATCH')
    before = snapshot()
    if expected is not None and expected != before:
        raise PlanCompletionError('COMPLETED_PLAN_CHANGED')
    completed = subprocess.run([python or sys.executable, str(command), '--project-root', str(project)],
        cwd=code, text=True, capture_output=True, timeout=120)
    try:
        result = json.loads(completed.stdout)
    except (ValueError, TypeError) as exc:
        raise PlanCompletionError('OWNER_VALIDATION_RESPONSE_INVALID') from exc
    if completed.returncode or not isinstance(result, dict) or result.get('contract_version') != 'plan-actionability/v1' or result.get('plan_status') != 'PLAN_READY' or result.get('findings') != []:
        raise PlanCompletionError('OWNER_PLAN_INCOMPLETE')
    checked_code(code, code_commit)
    if snapshot() != before:
        raise PlanCompletionError('PLAN_CHANGED_DURING_VALIDATION')
    return {'plan_status': 'PLAN_READY', 'production_code_commit': code_commit,
            'plan': str(plan), 'artifacts': before, 'owner_verification': result,
            'external_effects_authorized': False}
