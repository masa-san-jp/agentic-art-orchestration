"""Card excerpts of Phase A v2: normalize them and prove they come from the pinned blob.

A knowledge base exports ``card: [{text, source_locator, source_sha256}]``. Before a run
uses a card, the text must appear verbatim (after one fixed normalization of both sides)
in the Git blob at the signal's own commit, and the blob's sha256 must be the exported one.
A mismatch is the owner's export being inconsistent; it is never silently dropped.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Callable

from tools.theme_sources import ROOT, _document, _git
from tools.validate import load_yaml

MIN_EXCERPT, MAX_EXCERPT, MAX_EXCERPTS, MAX_CARD_BYTES = 12, 120, 2, 420

BlobSource = Callable[[str, str, str], bytes]


class PhaseABlocked(ValueError):
    """A named stop of Phase A (design 7.4); ``reason`` is the code and ``details`` its evidence."""

    def __init__(self, reason: str, **details):
        super().__init__(reason)
        self.reason = reason
        self.details = details


# Design 4.1 fixed display rule, identical to art-history ``tools/card_excerpts.py``
# (``normalize_text`` / ``normalized_paragraphs`` / ``excerpt_in``): quote marks, link syntax,
# URLs and IDs are removed; a line break between ASCII characters becomes one space, any other
# line break is closed up. ``tests/test_phase_a_checks.py`` pins both sides to the same vectors.
_LINK = re.compile(r'!?\[([^\]]*)\]\([^)\s]*\)')
_URL = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'*+,;=%]+")
_ID = re.compile(r'(?<![A-Za-z0-9])[PQ]\d{2,}(?![A-Za-z0-9])'
                 r'|(?<![A-Za-z0-9/])(?:movement|person|place|concept|event|org|work|source)/[a-z0-9][a-z0-9-]*'
                 r'|urn:[a-z]+:\S+')
_EMPTY_BRACKETS = re.compile(r'[（(]\s*[）)]')


def normalize_text(text: str) -> str:
    text = _LINK.sub(r'\1', text)
    joined = ''
    for line in text.split('\n'):
        line = re.sub(r'^\s*(?:>\s*)+', '', line).strip()
        if not line:
            continue
        if joined and joined[-1].isascii() and line[0].isascii():
            joined += ' '
        joined += line
    for pattern in (_URL, _ID, _EMPTY_BRACKETS):
        joined = pattern.sub('', joined)
    return re.sub(r' {2,}', ' ', joined).strip()


def normalized_paragraphs(text: str) -> list[str]:
    return [p for p in (normalize_text(part) for part in re.split(r'\n\s*\n', text)) if p]


def excerpt_in(excerpt: str, paragraphs: list[str]) -> bool:
    """An excerpt must sit inside one normalized paragraph (art-history checks it the same way)."""
    return bool(excerpt) and '\n' not in excerpt and any(excerpt in p for p in paragraphs)


def git_blob_source(workspace_root: Path) -> BlobSource:
    """Read blobs at a pinned commit from the owner's checkout, never from its working tree."""
    owners = {item['id']: item for item in load_yaml(ROOT / 'config/repositories.yaml')['repositories']}

    def read(repository: str, commit: str, path: str) -> bytes:
        return _git(workspace_root / owners[repository]['path'], 'cat-file', 'blob', f'{commit}:{path}')

    return read


def verify_card(signal: dict, item: dict, read: BlobSource) -> str:
    """Return the normalized excerpt when the pinned blob contains it, else raise CARD_SOURCE_MISMATCH."""
    locator = item['source_locator']
    where = {'signal_id': signal['signal_id'], 'locator': locator}
    path = locator.split('#', 1)[0]
    if not path or path.startswith('/') or '..' in Path(path).parts:
        raise PhaseABlocked('CARD_SOURCE_MISMATCH', **where, detail='unsafe locator')
    source = signal['source']
    try:
        raw = read(source['repository'], source['commit'], path)
        body = _document(raw)[1]
    except (OSError, ValueError, KeyError, UnicodeDecodeError):
        raise PhaseABlocked('CARD_SOURCE_MISMATCH', **where, detail='blob unreadable') from None
    if hashlib.sha256(raw).hexdigest() != item['source_sha256']:
        raise PhaseABlocked('CARD_SOURCE_MISMATCH', **where, detail='blob sha256 differs')
    excerpt = normalize_text(item['text'])
    if not excerpt_in(excerpt, normalized_paragraphs(body)):
        raise PhaseABlocked('CARD_SOURCE_MISMATCH', **where, detail='excerpt not in blob')
    return excerpt


def check_all_cards(signals: list[dict], read: BlobSource) -> list[dict]:
    """Verify every card excerpt of every signal; return one evidence row per mismatch (empty = all pass)."""
    rows = []
    for signal in signals:
        domain = next(iter(signal.get('domain', {}).values()), None) or {}
        for item in domain.get('card') or []:
            try:
                verify_card(signal, item, read)
            except PhaseABlocked as blocked:
                rows.append({'reason': blocked.reason, **blocked.details})
    return rows


def main(argv: list[str] | None = None) -> int:
    """``python -m tools.card_sources --signals <ingest output dir> --workspace-root <pinned workspace>``."""
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description='Verify every card excerpt against the pinned blobs.')
    parser.add_argument('--signals', type=Path, required=True, help='directory written by tools/ingest_signals.py')
    parser.add_argument('--workspace-root', type=Path, required=True)
    args = parser.parse_args(argv)
    paths = sorted(args.signals.glob('*/*.json'))
    signals = [json.loads(path.read_text(encoding='utf-8')) for path in paths]
    signals = [signal for signal in signals if isinstance(signal, dict) and 'signal_id' in signal]
    cards = sum(len(next(iter(s.get('domain', {}).values()), {}).get('card') or []) for s in signals)
    rows = check_all_cards(signals, git_blob_source(args.workspace_root))
    for row in rows:
        print(json.dumps(row, ensure_ascii=False, sort_keys=True), file=sys.stderr)
    print(json.dumps({'status': 'FAILED' if rows else 'PASSED', 'signals': len(signals), 'cards': cards,
                      'mismatches': len(rows)}, ensure_ascii=False, sort_keys=True))
    return 1 if rows else 0


if __name__ == '__main__':
    raise SystemExit(main())
