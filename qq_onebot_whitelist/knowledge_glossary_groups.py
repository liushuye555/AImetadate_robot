"""Presentation-only grouping for repeated glossary terms."""
from __future__ import annotations

import unicodedata


def normalize(text: object) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return "".join(value.split())


def normalize_meaning(text: object) -> str:
    """Normalize presentation whitespace without changing technical casing."""
    value = unicodedata.normalize("NFKC", str(text or "")).strip()
    return " ".join(value.split())


def group_glossary(rows: list[dict]) -> list[dict]:
    """Group term spellings within a scope, keeping distinct meanings apart."""
    groups: dict[tuple[str, str], dict] = {}
    variants: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        scope = str(row.get("scope") or "")
        term = str(row.get("term") or "")
        term_key = (scope, normalize(term))
        if not term_key[1]:
            continue
        group = groups.setdefault(term_key, {"scope": scope, "term": term.strip(), "spellings": [], "variants": []})
        if term.strip() and term.strip() not in group["spellings"]:
            group["spellings"].append(term.strip())
        meaning = str(row.get("meaning") or "")
        variant_key = (*term_key, normalize_meaning(meaning))
        variant = variants.get(variant_key)
        if variant is None:
            variant = dict(row)
            variant["evidence_ids"] = []
            variant["inference_evidence"] = []
            variant["definition_evidence"] = []
            variant["alternatives"] = []
            variant["aliases"] = []
            variants[variant_key] = variant
            group["variants"].append(variant)
        # Preserve manual authority; merging repeated evidence never changes confidence.
        if row.get("origin") == "user":
            variant.update({key: row.get(key) for key in ("meaning", "origin", "status", "inference_kind", "inference_note")})
        elif variant.get("origin") != "user":
            # A repeated row may add evidence, but a weaker duplicate cannot
            # inherit an active state from a stronger duplicate.
            if row.get("status") != "active" or variant.get("status") != "active":
                variant["status"] = "candidate"
            kinds = {variant.get("inference_kind"), row.get("inference_kind")}
            if "unconfirmed" in kinds:
                variant["inference_kind"] = "unconfirmed"
                variant["inference_note"] = ""
            elif "ambiguous" in kinds:
                variant["inference_kind"] = "ambiguous"
        for field in ("evidence_ids",):
            value = row.get(field, [])
            if isinstance(value, list):
                variant[field] = sorted(set(variant[field]) | {item for item in value if type(item) is int and item > 0})
        for field in ("inference_evidence", "definition_evidence"):
            value = row.get(field, [])
            if isinstance(value, list):
                known = {(item.get("message_id"), item.get("quote")) for item in variant[field] if isinstance(item, dict)}
                for item in value:
                    if isinstance(item, dict) and (item.get("message_id"), item.get("quote")) not in known:
                        variant[field].append(dict(item))
                        known.add((item.get("message_id"), item.get("quote")))
        for field in ("alternatives",):
            value = row.get(field, [])
            if isinstance(value, list):
                for item in value:
                    if item not in variant[field]:
                        variant[field].append(item)
        # Only display an alias if its exact spelling is present in validated source quotes.
        cited = set(row.get("evidence_ids", [])) if isinstance(row.get("evidence_ids"), list) else set()
        quotes = [item.get("quote", "") for item in row.get("inference_evidence", [])
                  if isinstance(item, dict) and type(item.get("message_id")) is int
                  and item["message_id"] in cited]
        for alias in row.get("aliases", []) if isinstance(row.get("aliases"), list) else []:
            if isinstance(alias, str) and alias.strip() and any(alias.casefold() in quote.casefold() for quote in quotes):
                if alias not in variant["aliases"]:
                    variant["aliases"].append(alias)
    return list(groups.values())
