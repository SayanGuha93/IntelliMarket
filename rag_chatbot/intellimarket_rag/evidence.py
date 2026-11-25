"""Authoritative SQLite evidence and a fact-only model response contract."""

import json
import re
from contextlib import closing
from urllib.parse import urlsplit

from .hybrid import HybridSearch, evidence_terms
from .intent import object_schema
from .semantic import open_catalog


ATTRIBUTES = {
    "pockets": ("number of pockets", "pockets", "pocket", "pocket type"),
    "material": ("fabric", "material", "outer material", "body material", "base material",
                 "primary material", "top fabric", "bottom fabric", "dupatta fabric"),
    "closure": ("closure", "fastening type", "top closure", "bottom closure"),
    "pattern": ("pattern", "print or pattern type", "top pattern", "bottom pattern"),
    "sleeves": ("sleeve", "sleeve length", "sleeve styling"),
    "size": ("size", "body or garment size", "garment measurements"),
    "care": ("wash care", "care instructions", "wash type"),
    "waterproof": ("waterproof", "water resistant", "water resistance"),
}
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")
UNSAFE_VALUE = re.compile(
    r"\b(?:ignore (?:all |the |previous )?instructions|system prompt|api key|"
    r"in stock|available now|current price|live price)\b|https?://",
    re.I,
)
DISPLAY_ATTRIBUTES = {key for keys in ATTRIBUTES.values() for key in keys} | {
    "occasion", "fit", "type", "ideal for", "color", "colour", "outer material", "sole material",
    "width", "height", "depth", "capacity", "pack of", "dimensions", "fastening",
}
INCOMPLETE_VALUE = re.compile(r"(?:\b(?:in|of|with|for|to|and|or|including|such as)|[:;,]|\.\.\.|…)$", re.I)
MAX_EVIDENCE = 8
PLAN_SCHEMA = object_schema({
    "selections": {"type": "array", "minItems": 1, "maxItems": MAX_EVIDENCE, "items": object_schema({
        "evidence_id": {"type": "string"},
        "fields": {"type": "array", "maxItems": 4, "items": {"type": "string"}},
    })},
})


def safe_text(value):
    return CONTROL.sub(" ", str(value))


def safe_url(value):
    try:
        uri = urlsplit(value or "")
        host = uri.hostname or ""
        if (uri.scheme in {"http", "https"} and not uri.username and not uri.password
                and (host == "flipkart.com" or host.endswith(".flipkart.com"))
                and not CONTROL.search(value)):
            return value
    except ValueError:
        pass
    return None


def evidence_from_catalog(catalog, ids):
    order = list(dict.fromkeys(ids))[:MAX_EVIDENCE]
    if not order:
        return []
    with closing(open_catalog(catalog)) as connection:
        placeholders = ",".join("?" for _ in order)
        rows = {row["id"]: dict(row) for row in connection.execute(
            f"SELECT * FROM products WHERE id IN ({placeholders})", order
        )}
        hydrated = HybridSearch.results(connection, [rows[pid] for pid in order], {}, {})
    return [assemble(row) for row in hydrated]


def assemble(row):
    product = row["product"]
    platform = product["platform"]
    facts = {f"attribute:{key}": values for key, values in json.loads(product["attributes"]).items()}
    facts.update({field: product[field] for field in ("brand", "colour", "rating", "rating_count")
                  if product[field] is not None})
    if product["overall_rating"] is not None:
        facts["overall_rating"] = product["overall_rating"]
    if product["price_minor"] is not None:
        facts[product["price_field"]] = product["price_minor"]
    if product["retail_price_minor"] is not None:
        facts["retail_price"] = product["retail_price_minor"]
    categories = json.loads(product["category_path"])
    if categories:
        facts["category"] = categories
    return {
        "evidence_id": f"{platform}:{product['source_id']}",
        "id": product["id"], "source_id": product["source_id"], "platform": platform,
        "name": product["name"], "facts": facts, "category_basis": product["category_basis"],
        "description": product["description"], "conflicts": json.loads(product["conflicts"]),
        "source_file": row["source"]["file"],
        "records": [{**record, "product_url": safe_url(record["product_url"])}
                    for record in row["source"]["records"]],
    }


def preferred_fields(evidence, text):
    terms = evidence_terms(text)
    facts = evidence["facts"]
    attributes = [field for field in facts if field.startswith("attribute:") and displayable(evidence, field)]
    attributes.sort(key=lambda field: -len(terms & evidence_terms(
        field + " " + " ".join(facts[field])
    )))
    return [f for f in ("brand", "colour") if f in facts] + attributes[:4]


def displayable(evidence, field):
    return field.removeprefix("attribute:") in DISPLAY_ATTRIBUTES and all(
        is_complete_attribute(value) for value in evidence["facts"][field]
    )


def is_complete_attribute(value):
    if not isinstance(value, str):
        return False
    value = value.strip()
    return (0 < len(value) <= 220 and not UNSAFE_VALUE.search(value) and not CONTROL.search(value)
            and not INCOMPLETE_VALUE.search(value) and value.count("(") == value.count(")"))


def rating_display(value):
    return f"{value:.2f}"


def prompt_evidence(evidence, text, budget, *, max_products=MAX_EVIDENCE, max_fields=6):
    """Return a bounded prompt projection with a precise field allowlist."""
    snippets, disclosed = [], {}
    for item in evidence[:max_products]:
        fields = dict.fromkeys(preferred_fields(item, text)[:max_fields])
        selected = {field: item["facts"][field] for field in fields if field in item["facts"]}
        # A field too large for the prompt can still be rendered deterministically.
        selected = {field: value for field, value in selected.items()
                    if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) <= 220}
        record = {"evidence_id": item["evidence_id"], "title": item["name"][:180], "facts": selected}
        if len(json.dumps([*snippets, record], ensure_ascii=False).encode("utf-8")) > budget:
            break
        snippets.append(record)
        disclosed[item["evidence_id"]] = set(selected)
    return snippets, disclosed


class PlanValidationError(ValueError):
    def __init__(self, category, path):
        super().__init__(f"{category} at {path}")
        self.details = {"category": category, "path": path}


def validate_plan(plan, disclosed):
    """Accept only evidence IDs and field selectors. No generated facts or prose."""
    if not isinstance(plan, dict):
        raise PlanValidationError("wrong_type", "$")
    if "selections" not in plan:
        raise PlanValidationError("missing_required", "$.selections")
    if set(plan) != {"selections"}:
        raise PlanValidationError("unexpected_fields", "$")
    rows = plan["selections"]
    if not isinstance(rows, list):
        raise PlanValidationError("wrong_type", "$.selections")
    if not 1 <= len(rows) <= MAX_EVIDENCE:
        raise PlanValidationError("invalid_count", "$.selections")
    selected = {}
    for index, row in enumerate(rows):
        path = f"$.selections[{index}]"
        if not isinstance(row, dict):
            raise PlanValidationError("wrong_type", path)
        for key in ("evidence_id", "fields"):
            if key not in row:
                raise PlanValidationError("missing_required", f"{path}.{key}")
        if set(row) != {"evidence_id", "fields"}:
            raise PlanValidationError("unexpected_fields", path)
        identifier, fields = row["evidence_id"], row["fields"]
        if not isinstance(identifier, str) or identifier not in disclosed:
            raise PlanValidationError("unknown_evidence_id", f"{path}.evidence_id")
        if identifier in selected:
            raise PlanValidationError("duplicate_evidence_id", f"{path}.evidence_id")
        if not isinstance(fields, list):
            raise PlanValidationError("wrong_type", f"{path}.fields")
        if len(fields) > 4:
            raise PlanValidationError("invalid_count", f"{path}.fields")
        for field_index, field in enumerate(fields):
            if not isinstance(field, str) or field not in disclosed[identifier]:
                raise PlanValidationError("undisclosed_field", f"{path}.fields[{field_index}]")
        if len(set(fields)) != len(fields):
            raise PlanValidationError("duplicate_field", f"{path}.fields")
        selected[identifier] = fields
    return selected


def amount(minor):
    return f"{minor // 100}.{minor % 100:02d}" if minor % 100 else str(minor // 100)


def format_fact(field, value):
    labels = {"price": "Myntra recorded price", "discounted_price": "Flipkart discounted price",
              "retail_price": "Flipkart retail price", "rating": "Recorded rating",
              "overall_rating": "Flipkart overall rating", "rating_count": "Rating count"}
    if field in {"price", "discounted_price", "retail_price"}:
        shown = amount(value)
    elif field in {"rating", "overall_rating"}:
        shown = rating_display(value)
    elif isinstance(value, list):
        shown = "; ".join(safe_text(entry) for entry in value)
    else:
        shown = safe_text(value)
    label = labels.get(field, field.removeprefix("attribute:").capitalize())
    return f"{safe_text(label)}: {shown}"


def citation(item):
    references = []
    for record in item["records"]:
        reference = f"row {record['record_number']}"
        if record["observed_at"]:
            reference += f", crawled {safe_text(record['observed_at'])[:10]} UTC"
        if record["product_url"]:
            reference += f", {record['product_url']}"
        references.append(reference)
    return f"[{safe_text(item['evidence_id'])} · {item['source_file']} · {'; '.join(references)}]"


def relevant_attribute_fields(item, attribute):
    facts = item["facts"]
    keys = ATTRIBUTES.get(attribute, ())
    if attribute == "rating":
        return [key for key in ("rating", "overall_rating", "rating_count") if key in facts]
    if attribute == "price":
        return [key for key in ("discounted_price", "retail_price", "price") if key in facts]
    if attribute == "colour":
        return ["colour"] if "colour" in facts else []
    return [f"attribute:{key}" for key in keys
            if f"attribute:{key}" in facts and displayable(item, f"attribute:{key}")]
