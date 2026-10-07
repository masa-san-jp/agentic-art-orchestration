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
        result = subprocess.run([sys.executable, str(script), 'element', '--help'], cwd=checkout,
                                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                timeout=timeout, check=False, env=child_environment())
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and 'next' in result.stdout and 'answer' in result.stdout


def relay(checkout: Path, operation: str, *, profile_root: Path, run_id: str,
          purpose: str, timeout: int) -> tuple[dict, dict]:
    command = [sys.executable, str(checkout / 'tools/growth_tasks.py'), 'element', operation,
               '--profile-root', str(profile_root), '--requester', run_id, '--purpose', purpose, '--json']
    result = subprocess.run(command, cwd=checkout, stdin=sys.stdin if operation == 'answer' else subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=timeout, check=False, env=child_environment())
    if result.returncode not in (0, 2):
        raise ValueError('PRIVATE_ELEMENT_TRANSPORT_FAILED')
    child = json.loads(result.stdout)
    if not isinstance(child, dict):
        raise ValueError('PRIVATE_ELEMENT_REPORT_INVALID')
    action = child.get('next_action')
    request = action.get('request') if isinstance(action, dict) else child.get('request')
    if isinstance(request, dict):
        # A compatible owner may add private itself; validate the shared message
        # and expose it only on stdout. Never instantiate the persistent Engine.
        request = {**request, 'private': True}
        require_message(request, 'element-request')
        child['next_action'] = {'kind': 'element', 'private': True, 'request': request}
        child.pop('request', None)
        progress = {'private': True, 'status': 'WAITING',
                    'run_id': request['run_id'], 'element_id': request['element_id'], 'attempt': request['attempt']}
    else:
        status = child.get('status')
        if status not in ('COMPLETED', 'BLOCKED'):
            raise ValueError('PRIVATE_ELEMENT_REPORT_INVALID')
        progress = {'private': True, 'status': status}
    # Ignore all unexpected report content, which could include owner raw values.
    public = {'outcome': 'offered' if progress['status'] == 'WAITING' else 'answered' if progress['status'] == 'COMPLETED' else 'unavailable', 'status': progress['status'], 'next_action': child.get('next_action') if request else None}
    return public, progress
