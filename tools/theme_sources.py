"""Read minimal public source text at the signal commit; never read Self Model raw data.

Normalized envelopes remain unchanged. Older owner pins export an evidence
locator and certainty summary but omit the evidence prose/target labels. These
read-only projections retain native text, locator and blob hash as provenance.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
import re
import subprocess

import yaml

from tools.process_policy import child_environment
from tools.validate import load_yaml

ROOT = Path(__file__).resolve().parents[1]


def _git(checkout, *args, input=None):
    result = subprocess.run(['git', *args], cwd=checkout, input=input, capture_output=True,
                            check=False, env=child_environment())
    if result.returncode:
        raise ValueError('PUBLIC_THEME_SOURCE_READ_FAILED')
    return result.stdout


def _document(raw):
    text = raw.decode('utf-8')
    match = re.match(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)', text, re.S)
    if not match:
        return {}, text
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        raise ValueError('PUBLIC_THEME_SOURCE_METADATA_INVALID') from None
    return meta if isinstance(meta, dict) else {}, text[match.end():]


def _evidence(body):
    # Take actual prose under evidence headings, never a predicted claim or URL
    # substituted for a summary. No LLM summarization is hidden in this step.
    blocks = re.split(r'(?m)^(#{1,6})\s+([^\n]+)\n', body)
    sections = []
    for index in range(1, len(blocks), 3):
        if re.search(r'根拠|\bevidence\b', blocks[index + 1], re.I):
            sections.append(blocks[index + 2].strip())
    return '\n'.join(part for part in sections if part)


def projections(signals: list[dict], workspace_root: Path) -> dict:
    manifest = load_yaml(ROOT / 'config/repositories.yaml')
    owners = {item['id']: item for item in manifest['repositories']}
    result = {'evidence': {}, 'targets': {}}
    for repository in ('art-history', 'marketing-trends'):
        rows = [signal for signal in signals if signal['source']['repository'] == repository]
        if not rows:
            continue
        commits = {row['source']['commit'] for row in rows}
        if len(commits) != 1:
            raise ValueError('PUBLIC_THEME_SOURCE_COMMIT_AMBIGUOUS')
        commit = next(iter(commits))
        owner = owners[repository]
        if commit != owner['observed_commit']:
            raise ValueError('PUBLIC_THEME_SOURCE_PIN_MISMATCH')
        checkout = workspace_root / owner['path']
        # Read Git blobs, not a mutable worktree or symlink target.
        records = []
        referenced = {locator.split('#', 1)[0] for row in rows for locator in row['source']['locators']}
        directories = [item['locator'].strip('/') for item in owner.get('knowledge_profile', {}).get('retrieval_entry_points', []) if item['kind'] == 'directory']
        for entry in _git(checkout, 'ls-tree', '-rz', commit).split(b'\0'):
            if not entry:
                continue
            header, path = entry.split(b'\t', 1)
            mode, kind, oid = header.split()
            locator = path.decode('utf-8')
            allowed = locator in referenced if repository == 'marketing-trends' else any(locator.startswith(directory + '/') for directory in directories)
            if allowed and kind == b'blob' and mode == b'100644' and locator.endswith('.md'):
                records.append((oid, locator))
        if not records:
            continue
        stream = io.BytesIO(_git(checkout, 'cat-file', '--batch', input=b''.join(oid + b'\n' for oid, _ in records)))
        referenced = {locator.split('#', 1)[0] for row in rows for locator in row['source']['locators']}
        targets = {rel['target_entity_id'] for row in rows
                   for rel in row.get('domain', {}).get('art_history', {}).get('relations', [])}
        for oid, locator in records:
            header = stream.readline().split()
            if len(header) != 3 or header[0] != oid or header[1] != b'blob':
                raise ValueError('PUBLIC_THEME_SOURCE_BLOB_MISMATCH')
            raw = stream.read(int(header[2]))
            if stream.read(1) != b'\n':
                raise ValueError('PUBLIC_THEME_SOURCE_BLOB_TRUNCATED')
            meta, body = _document(raw)
            ref = {'repository': repository, 'commit': commit, 'locator': locator,
                   'sha256': hashlib.sha256(raw).hexdigest()}
            if repository == 'art-history' and meta.get('id') in targets:
                label = meta.get('label_ja') or meta.get('label_en')
                if isinstance(label, str) and label.strip():
                    result['targets'][meta['id']] = {'text': label, 'source': ref}
            if repository == 'marketing-trends' and locator in referenced:
                evidence = _evidence(body)
                if evidence:
                    for row in rows:
                        if locator in [loc.split('#', 1)[0] for loc in row['source']['locators']]:
                            result['evidence'][row['signal_id']] = {'text': evidence, 'source': ref}
    return result
