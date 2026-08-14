#!/usr/bin/env python3
"""Export one approved child DTO through its normalized signal adapter."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable

try:
    from tools.adapters import adapt_art_history_signal, adapt_marketing_signal, adapt_self_model_signal
except ModuleNotFoundError:  # pragma: no cover - direct CLI fallback
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.adapters import adapt_art_history_signal, adapt_marketing_signal, adapt_self_model_signal


ADAPTERS: dict[str, Callable[[dict], dict]] = {
    "self": adapt_self_model_signal,
    "art-history": adapt_art_history_signal,
    "marketing": adapt_marketing_signal,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=sorted(ADAPTERS), required=True)
    parser.add_argument("--input", type=Path, required=True, help="approved derived child DTO; never raw source data")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        record = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            raise ValueError("input must be a JSON object")
        signal = ADAPTERS[args.kind](record)
        rendered = json.dumps(signal, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if args.check:
            if args.output.read_text(encoding="utf-8") != rendered:
                raise ValueError("generated signal differs; remediation: regenerate the normalized signal from the same child commit")
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        print(json.dumps({"command": "export-signal", "kind": args.kind, "status": "PASSED"}, sort_keys=True))
        return 0
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: export-signal: {exc}; remediation: provide one approved child DTO", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
