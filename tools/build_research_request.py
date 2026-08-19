#!/usr/bin/env python3
"""Turn a selected proposition into the research request the research repository accepts.

    python3 tools/build_research_request.py --proposition PR001 \
        --slug close-but-cannot-reach --title "近いのに届かない" \
        --requested-at 2026-08-20T07:00:00+09:00

The research repository has declared what it accepts (`research-request.schema.json`,
titled "Upstream research request") and a CLI that receives it. Nothing here
produced one, so a selected proposition stopped at this repository and the
research that followed was written by hand.

Values are copied from the proposition and its signals. Where the pipeline holds
nothing, the field is left null or empty rather than guessed: the research
repository can tell an empty field from an invented one, and a guessed intent
would steer the whole project.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    from tools.validate import load_json, load_yaml
except ModuleNotFoundError:  # pragma: no cover - direct CLI fallback
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.validate import load_json, load_yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "research-requests"
SNAPSHOT = ROOT / "data/snapshot.json"

SCHEMA_VERSION = "1.0.0"
SYSTEM = "agentic-art-orchestration"
# 研究段階では外に影響を出さない。要項の提出も公開もここでは許可しない。
PROHIBITED = ["publish", "submit", "send", "purchase", "contract", "delete"]
SCOPE_BY_KIND = {
    "self": "approved-personal-derived",
    "art-history": "external-knowledge",
    "marketing": "external-knowledge",
}


def _orchestration_commit() -> str:
    """The commit this request was composed at, so the research can be traced back."""
    import subprocess

    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    return head.stdout.strip() if head.returncode == 0 else "0" * 40


class RequestError(RuntimeError):
    """The proposition does not carry what the research repository requires."""


def _next_request_id(output: Path) -> str:
    existing = [int(match.group(1)) for path in output.glob("RR*.yaml")
                if (match := re.fullmatch(r"RR(\d{3,})", path.stem))]
    return f"RR{max(existing, default=0) + 1:03d}"


DOMAIN_BY_KIND = {"self": "self_model", "art-history": "art_history", "marketing": "marketing"}


def _bound_value(signal: dict, kind: str, attribute: str) -> str:
    """Read the attribute the slot binds, not the record's own summary.

    The slot names which attribute it spends. Falling back to the record's
    statement would put a description of the export into the question instead of
    what the export says.
    """
    domain = (signal.get("domain") or {}).get(DOMAIN_BY_KIND.get(kind, ""), {})
    value = domain.get(attribute)
    entity = (signal.get("source", {}).get("entity_ids") or [signal.get("signal_id", "")])[0]

    if isinstance(value, list) and value and isinstance(value[0], dict):
        # 関係は種類だけでは読めない。どの括りの、何に対する関係かまで言う
        relation = value[0]
        return f"{entity} の {relation.get('relation')} 関係（{relation.get('target_entity_id')}）"
    if isinstance(value, list) and value and isinstance(value[0], str):
        return value[0]
    if isinstance(value, str) and value:
        # 段階のような単語は、何がその段階にあるのかを添える
        return f"{entity} が {value} の段階にあること" if kind == "marketing" else value
    return signal.get("statement", signal.get("signal_id", ""))


def _creative_question(proposition: dict, signals: dict) -> str:
    """Fill the rule's own template with what each bound attribute actually says."""
    template = proposition["structured_output"]["template"]
    for slot, binding in proposition["structured_output"]["slots"].items():
        signal = signals.get(binding["signal_id"])
        value = _bound_value(signal, binding["signal_kind"], binding["attribute"]) if signal else binding["signal_id"]
        template = template.replace("{" + slot + "}", value)
    return template


def _reference_uri(signal: dict, locator: str, full_names: dict) -> str:
    """Point at the material where it can be opened, pinned to the commit it came from.

    The knowledge bases carry repository-relative locators. The research repository
    requires a URI, and a reference nobody can open is not a reference.
    """
    source = signal.get("source", {})
    full_name = full_names.get(source.get("repository"))
    if not full_name or not source.get("commit"):
        return f"urn:{source.get('repository', 'unknown')}:{locator}"
    return f"https://github.com/{full_name}/blob/{source['commit']}/{locator}"


def build_request(proposition: dict, signals: dict, *, request_id: str, slug: str, title: str,
                  requested_at: str, commit: str, deadline: str | None, creator_id: str | None,
                  full_names: dict | None = None) -> dict:
    kinds = {binding["signal_kind"] for binding in proposition["structured_output"]["slots"].values()}
    used = [signals[binding["signal_id"]] for binding in proposition["structured_output"]["slots"].values()
            if binding["signal_id"] in signals]

    full_names = full_names or {}
    references = []
    open_questions: list[str] = []
    for signal in used:
        for evidence in signal.get("evidence_refs", []):
            references.append({
                "label": signal["signal_id"],
                "uri": _reference_uri(signal, evidence["locator"], full_names),
                # 出典が公開引用可能かは、この段階では判定していない
                "rights_status": "UNKNOWN",
            })
        open_questions.extend(signal.get("unknowns", []))

    # 本人由来の派生情報が入っている限り、公開してよい前提は置かない
    personal = "self" in kinds
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "requested_at": requested_at,
        "source": {"kind": "REPOSITORY", "system": SYSTEM, "repository": f"masa-san-jp/{SYSTEM}", "commit": commit},
        "project": {"slug": slug, "title": title, "creator_id": creator_id},
        "intent": {
            "purpose": f"命題 {proposition['proposition_id']} が制作に耐えるかを確かめ、作るべきものを定める。",
            "creative_question": _creative_question(proposition, signals),
            "intended_use": "制作プランの作成に用いる。外部公開・提出は行わない。",
            # 鑑賞体験は調査の結果として決まる。ここで決めない
            "audience_experience": None,
            # 媒体も同じく、調査と作家の判断で決まる
            "medium_materials": [],
        },
        "constraints": {
            "deadline": deadline,
            "budget": None,
            "publication_scope": "PROJECT_INTERNAL" if personal else "PUBLIC_CITABLE",
            "allowed_source_scopes": sorted({SCOPE_BY_KIND[kind] for kind in kinds if kind in SCOPE_BY_KIND}),
            "prohibited_actions": PROHIBITED,
            "technical": [],
            "physical": [],
            "rights": [],
            "safety": [],
        },
        "references": references,
        "open_questions": sorted(set(open_questions)),
        "data_boundary": {
            "classification": "PRIVATE_DERIVED" if personal else "PROJECT_INTERNAL",
            "raw_data_included": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--propositions", type=Path, default=ROOT / "data/propositions.json")
    parser.add_argument("--proposition", help="省略時は先頭の命題を使う")
    parser.add_argument("--signals", type=Path, default=ROOT / "data/signals")
    parser.add_argument("--slug", required=True, help="作品の識別子。機械が名前を決めない")
    parser.add_argument("--title", required=True)
    parser.add_argument("--requested-at", required=True)
    parser.add_argument("--deadline")
    parser.add_argument("--creator-id")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    try:
        document = load_json(args.propositions)
        propositions = document["propositions"]
        proposition = next(
            (item for item in propositions if item["proposition_id"] == args.proposition),
            propositions[0] if not args.proposition else None,
        )
        if proposition is None:
            raise RequestError(f"proposition {args.proposition!r} is not in {args.propositions}")

        signals = {}
        for path in sorted(args.signals.glob("*/*.json")):
            signal = load_json(path)
            signals[signal["signal_id"]] = signal

        manifest = load_yaml(ROOT / "config/repositories.yaml")
        full_names = {item["id"]: item["full_name"] for item in manifest["repositories"]}
        snapshot = load_json(SNAPSHOT) if SNAPSHOT.is_file() else {}
        commit = _orchestration_commit()

        args.output.mkdir(parents=True, exist_ok=True)
        request_id = _next_request_id(args.output)
        request = build_request(
            proposition, signals, request_id=request_id, slug=args.slug, title=args.title,
            requested_at=args.requested_at, commit=commit, deadline=args.deadline, creator_id=args.creator_id,
            full_names=full_names,
        )
    except (RequestError, OSError, KeyError, IndexError) as exc:
        print(json.dumps({"status": "FAILED", "detail": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1

    destination = args.output / f"{request_id}.yaml"
    import yaml

    destination.write_text(yaml.safe_dump(request, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(json.dumps({"status": "PASSED", "request_id": request_id, "path": str(destination)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
