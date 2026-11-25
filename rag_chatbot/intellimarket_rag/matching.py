"""Conservative cross-platform identity decisions over the two source catalogs."""

import json
import re
from collections import defaultdict
from contextlib import closing

from .hybrid import evidence_terms
from .query import Query, normalized
from .semantic import PRICE_NOTICE, open_catalog


TYPES = {
    "t-shirt": r"\bt[ -]?shirts?\b", "shirt": r"\bshirts?\b",
    "kurta": r"\bkurtas?\b", "jacket": r"\bjackets?\b", "jeans": r"\bjeans\b",
    "bra": r"\bbras?\b", "dress": r"\bdress(?:es)?\b", "saree": r"\bsarees?\b",
    "shorts": r"\bshorts\b", "top": r"\btops?\b", "backpack": r"\bbackpacks?\b",
    "shoe": r"\b(?:shoes?|sneakers?|trainers?)\b", "sandals": r"\bsandals?\b",
    "lehenga": r"\blehengas?\b", "necklace": r"\bnecklaces?\b",
    "palazzo": r"\bpalazzos?\b", "trousers": r"\b(?:trousers|chinos)\b",
}
CODE_KEYS = {"model id", "model number", "model no", "style code", "manufacturer part number"}
DESCRIPTORS = {"denim", "cycling", "floral", "cotton", "leather", "formal", "waterproof"}
VARIANTS = {
    "material": {"fabric", "material", "outer material", "body material"},
    "size": {"size", "clothing size"}, "pattern": {"pattern", "top pattern"},
    "pack": {"pack of", "number of contents in sales package", "pack size"},
    "capacity": {"capacity", "storage capacity", "mug capacity"},
    "sleeve": {"sleeve", "sleeve length"}, "fit": {"fit"}, "neck": {"neck"},
    "length": {"length"}, "closure": {"closure"}, "heel height": {"heel height"},
}


def compact(value):
    return re.sub(r"[\W_]+", "", normalized(value))


def profile(product):
    attributes = json.loads(product["attributes"])
    name = normalized(product["name"])
    title_types = {label for label, pattern in TYPES.items() if re.search(pattern, name)}
    if "t-shirt" in title_types:
        title_types.discard("shirt")
    categories = json.loads(product["category_path"])
    category_types = {label for label, pattern in TYPES.items()
                      if any(re.search(pattern, normalized(part)) for part in categories)}
    if "t-shirt" in category_types:
        category_types.discard("shirt")
    codes = {compact(value) for label, values in attributes.items() if label in CODE_KEYS
             for value in values if len(compact(value)) >= 5 and re.search(r"\d", value)}
    codes_by_field = {
        label: {compact(value) for value in attributes.get(label, [])} & codes for label in CODE_KEYS
    }
    conflicts = set(json.loads(product["conflicts"]))
    variants = {
        label: {compact(value) for field in fields for value in attributes.get(field, [])}
        for label, fields in VARIANTS.items()
    }
    # Prefer explicit source colour over context-dependent colour mentions in text.
    variants["colour"] = {compact(product["colour"])} if product["colour"] else set()
    return {
        "brand": normalized(product["brand"] or ""),
        "types": title_types or category_types, "category_types": category_types,
        "codes": codes, "codes_by_field": codes_by_field, "variants": variants,
        "conflicts": conflicts, "name": evidence_terms(name),
    }


def assess(left, right, similarity=None):
    a, b = profile(left), profile(right)
    compatible_type = bool(a["types"] & b["types"])
    same_brand = bool(a["brand"] and a["brand"] == b["brand"])
    variant_conflicts = sorted(
        field for field in a["variants"]
        if a["variants"][field] and b["variants"][field]
        and a["variants"][field].isdisjoint(b["variants"][field])
    )
    variant_agreement = sorted(
        field for field in a["variants"] if a["variants"][field] & b["variants"][field]
    )
    shared_codes = sorted(a["codes"] & b["codes"])
    shared_descriptors = sorted(a["name"] & b["name"] & DESCRIPTORS)
    union = a["name"] | b["name"]
    overlap = len(a["name"] & b["name"]) / len(union) if union else 0.0
    identity_field_conflicts = sorted(
        field for field in a["conflicts"] | b["conflicts"]
        if field in {"name", "brand", "colour", "categories"} or field.startswith("attributes.")
    )
    category_conflict = bool(a["category_types"] and b["category_types"]
                             and a["category_types"].isdisjoint(b["category_types"]))
    code_conflict = bool(a["codes"] and b["codes"] and a["codes"].isdisjoint(b["codes"])) or any(
        a["codes_by_field"][field] and b["codes_by_field"][field]
        and a["codes_by_field"][field].isdisjoint(b["codes_by_field"][field]) for field in CODE_KEYS
    )
    reliable = (same_brand and compatible_type and shared_codes and overlap >= 0.65
                and {"colour", "material"}.issubset(variant_agreement) and not variant_conflicts
                and not identity_field_conflicts and not category_conflict and not code_conflict)
    if reliable:
        status = "identical"
    elif same_brand and compatible_type and (shared_codes or overlap >= 0.70) and not (
            variant_conflicts or code_conflict or category_conflict):
        status = "ambiguous"
    elif compatible_type and (same_brand or shared_descriptors
                              or overlap >= 0.30 or (similarity or 0) >= 0.72):
        status = "similar"
    else:
        status = "no_reliable_match"
    return {
        "status": status, "same_brand": same_brand, "compatible_category": compatible_type,
        "category_conflict": category_conflict, "shared_codes": shared_codes, "code_conflict": code_conflict,
        "variant_agreement": variant_agreement, "variant_conflicts": variant_conflicts,
        "source_identity_conflicts": identity_field_conflicts, "title_overlap": overlap,
        "shared_descriptors": shared_descriptors,
    }


def compare(service, query, *, top_k=5):
    from .query import QueryError, validate

    validate(query)
    if not query.comparison or not 1 <= top_k <= 30:
        raise QueryError("Provide comparison intent and a top-k between 1 and 30.")
    anchors = service.search(Query(platform=query.platform, product_id=query.product_id), top_k=1)
    output = {"status": "no_reliable_match", "anchor": anchors[0] if anchors else None,
              "candidates": [], "reliable_match": None, "price_notice": PRICE_NOTICE}
    if not anchors:
        return output
    anchor = anchors[0]["product"]
    target = "myntra" if anchor["platform"] == "flipkart" else "flipkart"
    ranked = service.search(Query(terms=anchor["name"], platform=target), top_k=50)
    if anchor["brand"]:
        ranked.extend(service.search(Query(terms=anchor["name"], platform=target, brand=anchor["brand"]), top_k=30))
    # Search code-sharing candidates independently of rank cutoffs.
    evidence = profile(anchor)
    hints = (evidence["name"] & DESCRIPTORS) | evidence["types"]
    if len(hints) >= 2:
        alternatives = service.search(Query(terms=" ".join(sorted(hints)), platform=target),
                                      mode="fts", top_k=30)
        ranked.extend(alternatives)
    if evidence["brand"] and evidence["codes"]:
        with closing(open_catalog(service.catalog)) as connection:
            rows = connection.execute(
                "SELECT * FROM products WHERE platform=? AND brand_key=?",
                (target, evidence["brand"]),
            )
            code_matches = [dict(row) for row in rows if evidence["codes"] & profile(row)["codes"]]
            for offset in range(0, len(code_matches), 100):
                ranked.extend(service.results(connection, code_matches[offset:offset + 100], {}, {}))
    evaluated = []
    for candidate in {item["product"]["id"]: item for item in reversed(ranked)}.values():
        decision = assess(anchor, candidate["product"], candidate["similarity"])
        if decision["status"] != "no_reliable_match":
            evaluated.append({**candidate, "evidence": decision})
    priority = {"identical": 0, "ambiguous": 1, "similar": 2}
    evaluated.sort(key=lambda item: (priority[item["evidence"]["status"]],
                                     not item["evidence"]["same_brand"],
                                     -(item["similarity"] or 0),
                                     -item["evidence"]["title_overlap"], item["product"]["id"]))
    exact = [item for item in evaluated if item["evidence"]["status"] == "identical"]
    if len(exact) == 1:
        output.update(status="identical", reliable_match=exact[0])
    elif evaluated:
        output["status"] = "ambiguous" if len(exact) > 1 else evaluated[0]["evidence"]["status"]
    output["candidates"] = evaluated[:top_k]
    return output


def audit_identity(catalog):
    """Exhaustively examine the cross-platform pairs eligible for the identity rule."""
    index = defaultdict(list)
    pairs, verified = set(), []
    with closing(open_catalog(catalog)) as connection:
        for row in connection.execute("SELECT * FROM products WHERE platform='myntra' AND brand_key<>''"):
            candidate = dict(row)
            p = profile(candidate)
            for code in p["codes"]:
                index[p["brand"], code].append(candidate)
        for row in connection.execute("SELECT * FROM products WHERE platform='flipkart' AND brand_key<>''"):
            anchor = dict(row)
            p = profile(anchor)
            for code in p["codes"]:
                for candidate in index[p["brand"], code]:
                    pair = anchor["id"], candidate["id"]
                    if pair in pairs:
                        continue
                    pairs.add(pair)
                    if assess(anchor, candidate)["status"] == "identical":
                        verified.append([anchor["source_id"], candidate["source_id"]])
    return {"shared_brand_and_code_pairs": len(pairs), "rule_supported_identical_pairs": verified}
