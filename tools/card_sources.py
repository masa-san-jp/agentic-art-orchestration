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


def _ascii_alnum(char: str) -> bool:
    return char.isascii() and char.isalnum()


def normalize_text(value: str) -> str:
    """The fixed display/verification rule (design 4.1).

    Quote markers, Markdown links, URLs and IDs such as ``P571`` are removed; a line break
    between two Latin letters becomes one space and any other line break disappears.
    """
    text = re.sub(r'(?m)^[ \t]*>+[ \t]?', '', value.replace('\r\n', '\n'))
    text = re.sub(r'\[([^\]\n]*)\]\([^)\n]*\)', r'\1', text)
    text = re.sub(r'https?://[^\s<>)\]]+', '', text)
    text = re.sub(r'(?<![A-Za-z0-9])[PQ]\d{3,}(?![A-Za-z0-9])', '', text)

    def join(match):
        before, after = text[match.start() - 1:match.start()], text[match.end():match.end() + 1]
        return ' ' if before and after and _ascii_alnum(before) and _ascii_alnum(after) else ''

    return re.sub(r'[ \t]*\n\s*', join, text)


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
    if excerpt not in normalize_text(body):
        raise PhaseABlocked('CARD_SOURCE_MISMATCH', **where, detail='excerpt not in blob')
    return excerpt
