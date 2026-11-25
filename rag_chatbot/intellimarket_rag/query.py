"""Deterministic intent grammar; callers may also supply a typed intent."""

import re
import unicodedata
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation

from .attributes import FACETS, AttributeConstraintError, canonical_facet, extract_attributes


class QueryError(ValueError):
    """An unsupported, contradictory, or incomplete user constraint."""


@dataclass(frozen=True)
class Bound:
    value: Decimal
    inclusive: bool = True


@dataclass(frozen=True)
class Query:
    terms: str = ""
    name: str | None = None
    product_id: str | None = None
    platform: str | None = None
    brand: str | None = None
    colour: str | None = None
    category: str | None = None
    price_min: Bound | None = None
    price_max: Bound | None = None
    rating_min: Bound | None = None
    rating_max: Bound | None = None
    count_min: Bound | None = None
    count_max: Bound | None = None
    price_field: str = "recorded"
    sort: str | None = None
    comparison: bool = False
    fabric: str | None = None
    bottom_fabric: str | None = None
    material: str | None = None
    gender: str | None = None
    pattern: str | None = None
    occasion: str | None = None
    closure: str | None = None


SORTS = {"name", "price-asc", "price-desc", "rating-desc", "count-desc"}
OPERATORS = (">=", "<=", ">", "<", "=")
NUMERIC = r"\d+(?:,\d{3})*(?:\.\d+)?"
FIELD_NAMES = {"price": "price", "rating": "rating", "rating-count": "count"}
WORDS = r'(?:[^\W_]+(?:-[^\W_]+)?)'
EXACT = {
    "platform": "platform", "brand": "brand", "colour": "colour", "color": "colour",
    "category": "category", "name": "name", "id": "product_id",
    "product-id": "product_id", "sort": "sort", "price-field": "price_field",
    **{field.replace("_", "-"): field for field in FACETS},
}


def normalized(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def validate(query):
    try:
        changes = {field: canonical_facet(field, getattr(query, field)) for field in FACETS
                   if getattr(query, field) is not None}
    except AttributeConstraintError as error:
        raise QueryError(str(error)) from error
    if changes:
        query = replace(query, **changes)
    if query.platform not in {None, "flipkart", "myntra"}:
        raise QueryError("Choose platform Flipkart or Myntra.")
    if query.sort is not None and query.sort not in SORTS:
        raise QueryError("Unknown sort order.")
    if query.price_field not in {"recorded", "retail"}:
        raise QueryError("Choose price-field:recorded or price-field:retail.")
    if query.price_field == "retail" and query.platform == "myntra":
        raise QueryError("Myntra has a recorded price only. Choose price-field:recorded.")
    if query.comparison and not (query.product_id and query.platform):
        raise QueryError("Comparison needs one source platform and product ID.")
    if not any((query.terms, query.name, query.product_id, query.platform, query.brand,
                query.colour, query.category, query.price_min, query.price_max,
                query.rating_min, query.rating_max, query.count_min, query.count_max, query.sort, changes)):
        raise QueryError("Provide products to search for or a catalog filter.")
    for field, maximum, scale in (("price", Decimal(2**63 - 1) / 100, 100),
                                  ("rating", Decimal(5), None),
                                  ("count", Decimal(2**63 - 1), 1)):
        lower, upper = getattr(query, field + "_min"), getattr(query, field + "_max")
        for bound in (lower, upper):
            if bound is None:
                continue
            value = bound.value
            if (not value.is_finite() or value < 0 or value > maximum
                    or (scale and value * scale != (value * scale).to_integral_value())):
                raise QueryError(f"Invalid {field} boundary.")
        if lower and upper and (lower.value > upper.value or (
                lower.value == upper.value and not (lower.inclusive and upper.inclusive))):
            raise QueryError(f"The {field} bounds conflict.")
    if query.comparison and any((query.terms, query.name, query.brand, query.colour, query.category,
                                 query.price_min, query.price_max, query.rating_min, query.rating_max,
                                 query.count_min, query.count_max, query.sort, changes,
                                 query.price_field != "recorded")):
        raise QueryError("Comparison accepts a source platform and product ID only.")
    if query.product_id and query.terms:
        raise QueryError("Use a product ID with explicit filters, or remove the ID to search by description.")
    return query


def parse_query(text):
    if not text.strip() or len(text) > 1500:
        raise QueryError("Enter a query of 1–1,500 characters.")
    parts = re.split(r';(?=(?:[^"]*"[^"]*")*[^"]*$)', text)
    fields = {}

    def put(field, value):
        if field in fields and fields[field] != value:
            raise QueryError(f"Conflicting {field.replace('_', ' ')} constraints.")
        fields[field] = value

    def boundary(field, operator, value):
        try:
            value = Decimal(value.replace(",", ""))
        except InvalidOperation as error:
            raise QueryError(f"Invalid {field} boundary.") from error
        if operator in {">", ">=", "="}:
            put(field + "_min", Bound(value, operator != ">"))
        if operator in {"<", "<=", "="}:
            put(field + "_max", Bound(value, operator != "<"))

    terms = parts[0].strip()
    if re.match(r'(?i)^(?:[\w-]+\s*:|(?:price|rating|rating-count)\s*[<>=])', terms):
        parts = ["", *parts]
        terms = ""
    for segment in parts[1:]:
        segment = segment.strip()
        constraint = re.fullmatch(rf"(price|rating-count|rating)\s*(>=|<=|=|>|<)\s*({NUMERIC})",
                                  segment, re.I)
        if constraint:
            field, operator, value = constraint.groups()
            boundary(FIELD_NAMES[field.lower()], operator, value)
            continue
        match = re.fullmatch(r'([\w-]+)\s*:\s*(?:"([^"]+)"|([^"]+))', segment)
        if not match or match[1].lower() not in EXACT:
            raise QueryError(f"Unsupported filter: {segment!r}. Use typed filters after semicolons.")
        field = EXACT[match[1].lower()]
        value = (match[2] or match[3]).strip()
        if not value:
            raise QueryError(f"Missing {field} value.")
        if field in FACETS:
            try:
                value = canonical_facet(field, value)
            except AttributeConstraintError as error:
                raise QueryError(str(error)) from error
        put(field, normalized(value) if field in {"platform", "sort", "price_field"} else value)

    if re.match(r"(?i)^compare\b", terms):
        put("comparison", True)
        terms = re.sub(r"(?i)^compare\s*", "", terms)

    if re.fullmatch(r'"[^"]+"', terms):
        put("name", terms[1:-1])
        terms = ""
    elif '"' in terms:
        raise QueryError("Use a quoted name by itself or add ; name:\"product name\".")

    def platform(match):
        put("platform", match[1].lower())
        return " "

    terms = re.sub(r"(?i)\b(?:on|from)\s+(flipkart|myntra)\b", platform, terms)

    def price_range(match):
        boundary("price", ">=", match[1])
        boundary("price", "<=", match[2])
        return " "

    terms = re.sub(rf"(?i)\bprice\s+between\s+({NUMERIC})\s+and\s+({NUMERIC})(?![\w.,])",
                   price_range, terms)
    for pattern, sort in (("cheapest first", "price-asc"), ("most expensive first", "price-desc"),
                          ("highest rated first", "rating-desc")):
        if re.search(rf"(?i)\b{pattern}\b", terms):
            put("sort", sort)
            terms = re.sub(rf"(?i)\b{pattern}\b", " ", terms)

    def limits(match):
        field, operator, value = match.groups()
        boundary(field.lower() if field else "price",
                 {"under": "<", "below": "<", "over": ">", "above": ">",
                  "at least": ">=", "at most": "<="}[normalized(operator)], value)
        return " "

    terms = re.sub(rf"(?i)\b(?:(price|rating|count)\s+)?(under|below|over|above|at least|at most)\s+({NUMERIC})(?![\w.,]|\s+(?:stars?|ratings?|reviews?|mm|cm|gb|tb|inches|years|kg)\b)", limits, terms)
    if re.search(r"(?i)\b(?:under|below|over|above|at least|at most|between|within)\s+(?:[₹$£€+-]|\d)|"
                 r"\b(?:rating|price|count)\s*[<>=]|\b(?:flipkart|myntra|versus|vs|cheapest|highest rated)\b|[<>₹$£€]", terms):
        raise QueryError("Use explicit platform, price, rating, rating-count or sort filters after semicolons.")
    if re.search(r"(?i)\b(?:brand|category|colour|color|rating count)\s*[:=]|\b(?:made by|by brand|in category|only|sort by|rated at)\b", terms):
        raise QueryError("Use an explicit brand, colour or category filter after a semicolon.")
    if re.search(r"(?i)\b(?:(?:min(?:imum)?|max(?:imum)?)\s+(?:price|rating|count|budget)|"
                 r"(?:less than|more than|up to)\s+\d|\d+(?:\.\d+)?\s+(?:stars?|reviews?|ratings?)|"
                 r"(?:on|from)\s+(?:amazon|ebay|best buy)|sort(?:ed)?\s+(?:by|in))\b", terms):
        raise QueryError("Use an explicit numeric, platform or sort filter after a semicolon.")
    terms = " ".join(terms.split())
    if terms and not re.search(WORDS, terms):
        raise QueryError("Search terms must contain letters or numbers.")
    try:
        inferred = extract_attributes(terms)
    except AttributeConstraintError as error:
        raise QueryError(str(error)) from error
    for field, value in inferred.items():
        if field == "colour" and field in fields and normalized(fields[field]) == value:
            continue
        put(field, value)
    return validate(Query(terms=terms, **fields))
