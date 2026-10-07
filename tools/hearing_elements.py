"""Private pass-through for a pinned Self Model element CLI.

No requests, answers or child diagnostics are saved here. The caller records
only progress metadata and streams the private request to the active agent.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from tools.element_contracts import require_message
from tools.process_policy import child_environment


def supports(checkout: Path, timeout: int) -> bool:
    """Probe the CLI, not a commit date or a guess about an unmerged child."""
    script = checkout / 'tools/growth_tasks.py'
    if not script.is_file():
        return False
    try:
        result = subprocess.run([*_command(checkout), 'element', '--help'], cwd=checkout,
                                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                timeout=timeout, check=False, env=child_environment())
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and 'next' in result.stdout and 'answer' in result.stdout


def _command(checkout: Path) -> list[str]:
    runtime = checkout / 'tools/agent_runtime.py'
    prefix = [sys.executable, str(runtime)] if runtime.is_file() else [sys.executable]
    return [*prefix, str(checkout / 'tools/growth_tasks.py')]


def relay(checkout: Path, operation: str, *, profile_root: Path, run_id: str,
          purpose: str, timeout: int, owner_answer: str | None = None,
          subject: str | None = None) -> tuple[dict, dict]:
    if operation not in {'next', 'answer', 'respond', 'confirm', 'skip'}:
        raise ValueError('PRIVATE_ELEMENT_OPERATION_INVALID')
    if operation == 'confirm' and owner_answer not in {'yes', 'no'}:
        raise ValueError('PRIVATE_ELEMENT_OPERATION_INVALID')
    command = [*_command(checkout), 'element', operation,
               '--profile-root', str(profile_root), '--run-id', run_id, '--purpose', purpose, '--json']
    if subject is not None:
        command += ['--subject', subject]
    if operation == 'confirm':
        command += ['--owner-answer', owner_answer]
    result = subprocess.run(command, cwd=checkout,
                            stdin=sys.stdin if operation in {'answer', 'respond'} else subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=timeout, check=False, env=child_environment())
    if result.returncode not in (0, 2):
        raise ValueError('PRIVATE_ELEMENT_TRANSPORT_FAILED')
    # Rejected/stale operations return a fixed ERROR on stderr. Reacquire the
    # owner's position, without saving diagnostics or consuming another answer.
    if result.returncode == 2 and not result.stdout.strip() and operation != 'next':
        report, progress = relay(checkout, 'next', profile_root=profile_root, run_id=run_id,
                                 purpose=purpose, timeout=timeout, subject=subject)
        report['operation_error'] = 'ELEMENT_OPERATION_REJECTED'
        return report, progress
    child = json.loads(result.stdout)
    if not isinstance(child, dict):
        raise ValueError('PRIVATE_ELEMENT_REPORT_INVALID')
    status = child.get('status')
    action = child.get('next_action')
    progress = {'private': True, 'status': status, 'run_id': run_id}
    exposed = None
    if status == 'WAITING':
        request = action.get('request') if isinstance(action, dict) else child.get('request')
        if not isinstance(request, dict):
            raise ValueError('PRIVATE_ELEMENT_REPORT_INVALID')
        request = {**request, 'private': True}
        require_message(request, 'element-request')
        if request['run_id'] != run_id:
            raise ValueError('PRIVATE_ELEMENT_REPORT_INVALID')
        exposed = {'kind': 'element', 'private': True, 'request': request, 'operation': 'answer'}
        progress.update(element_id=request['element_id'], attempt=request['attempt'])
    elif status in {'HEARING', 'CONFIRMATION', 'SEED_REQUIRED'}:
        fmt = 'yes-no' if status == 'CONFIRMATION' else 'event-block'
        if (not isinstance(action, dict) or action.get('kind') != 'hearing'
                or not isinstance(action.get('question'), str) or not action['question'].strip()
                or action.get('answer_format') != fmt):
            raise ValueError('PRIVATE_ELEMENT_REPORT_INVALID')
        exposed = {'kind': 'hearing', 'private': True, 'question': action['question'],
                   'why': action.get('why'), 'answer_format': fmt,
                   'operation': 'confirm' if status == 'CONFIRMATION' else 'respond'}
    elif status not in {'COMPLETED', 'BLOCKED', 'SKIPPED'}:
        raise ValueError('PRIVATE_ELEMENT_REPORT_INVALID')
    outcome = ('offered' if exposed else 'answered' if status == 'COMPLETED'
               else 'skipped' if status == 'SKIPPED' else 'unavailable')
    # Owner words are transient. Only the separate metadata dictionary persists.
    public = {'outcome': outcome, 'status': status, 'next_action': exposed}
    if status == 'BLOCKED':
        public['blocked'] = child.get('blocked')
    return public, progress
