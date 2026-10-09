"""Mechanical checks for the owner's exported relation edges, not KB semantics."""
import hashlib
import re
from tools.element import canonical


def validate_edges(value, vocabulary):
    if (not isinstance(value, dict) or set(value) != {'contract_version', 'vocabulary_sha256', 'source_sha256', 'edges'}
            or value['contract_version'] != 'operation-relation-edges/v1'
            or value['vocabulary_sha256'] != hashlib.sha256(canonical(vocabulary).encode()).hexdigest()
            or not isinstance(value['source_sha256'], str) or not re.fullmatch('[0-9a-f]{64}', value['source_sha256'])):
        raise ValueError('Invalid operation relation provenance')
    ids = {row['id'] for row in vocabulary['operations']}
    edges = value['edges']
    if not isinstance(edges, dict) or set(edges) != {'contrast', 'complement'}:
        raise ValueError('Invalid operation relation kinds')
    for kind, rows in edges.items():
        if not isinstance(rows, dict) or set(rows) != ids:
            raise ValueError('Incomplete operation relation coverage')
        for a, values in rows.items():
            if (not isinstance(values, list) or not values or any(not isinstance(b, str) for b in values)
                    or values != sorted(set(values)) or a in values or not set(values) <= ids):
                raise ValueError('Unknown, duplicate or self operation relation')
        for a, values in rows.items():
            if any(a not in rows[b] for b in values):
                raise ValueError('Asymmetric operation relation')
    if any(set(edges['contrast'][a]) & set(edges['complement'][a]) for a in ids):
        raise ValueError('Operation pair is both contrast and complement')
    return value
