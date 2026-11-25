"""Read and normalize the supplied source records without editing the CSVs."""

import ast
import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser


HEADERS = {
    "flipkart": frozenset("""
        uniq_id crawl_timestamp product_url product_name product_category_tree pid
        retail_price discounted_price brand description product_specifications
        product_rating overall_rating
    """.split()),
    "myntra": frozenset("""
        p_id name price colour brand ratingCount avg_rating description p_attributes img
    """.split()),
}

SPEC_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|\s+|=>|nil\b|true\b|false\b|[{}\[\],]|-?\d+(?:\.\d+)?')
NULLS = {"", "na", "n/a", "null", "none", "no rating available"}
MYNTRA_CATEGORIES = {
    "Kurta Sets": r"\bkurta\s+sets?\b",
    "Kurtas": r"\bkurtas?\b",
    "Jeans": r"\bjeans\b",
    "Jackets": r"\bjackets?\b",
    "Dresses": r"\bdress(?:es)?\b",
    "Sarees": r"\bsarees?\b",
    "T-Shirts": r"\bt[\s-]?shirts?\b",
    "Shirts": r"\bshirts?\b",
    "Tops": r"\btops?\b",
    "Trousers": r"\btrousers\b",
}


def clean(value):
    value = " ".join(value.split()) if isinstance(value, str) else ""
    return value if value.casefold() not in NULLS else None


def key(value):
    return unicodedata.normalize("NFKC", value or "").casefold()


class DescriptionParser(HTMLParser):
    blocks = {"br", "div", "li", "p", "ul", "ol", "tr", "td", "section"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = None

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden = tag
        if tag in self.blocks:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag == self.hidden:
            self.hidden = None
        if tag in self.blocks:
            self.parts.append(" ")

    def handle_data(self, data):
        if self.hidden is None:
            self.parts.append(data)


def strip_html(value):
    parser = DescriptionParser()
    parser.feed(value)
    parser.close()
    return clean("".join(parser.parts))


def parse_specs(value):
    """Tokenize Ruby hash syntax, transforming tokens only outside strings."""
    if len(value) > 100_000:
        raise ValueError("Specification payload exceeds parser limit")
    replacements = {"=>": ":", "nil": "null"}
    tokens = []
    position = 0
    while position < len(value):
        match = SPEC_TOKEN.match(value, position)
        if match is None:
            raise ValueError("Unsupported specification token")
        token = match.group()
        tokens.append(replacements.get(token, token))
        position = match.end()
    root = json.loads("".join(tokens))
    if not isinstance(root, dict) or "product_specification" not in root:
        raise ValueError("Expected product_specification")
    items = root["product_specification"]
    if items is None:
        return {}, []
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ValueError("Expected specification list")
    attributes, notes = {}, []
    for item in items:
        name, content = clean(item.get("key")), clean(item.get("value"))
        if name and content:
            attributes.setdefault(key(name), []).append(content)
        elif content:
            notes.append(content)
    return attributes, notes


def parse_attributes(value):
    if len(value) > 100_000:
        raise ValueError("Attribute payload exceeds parser limit")
    result = ast.literal_eval(value.strip())
    if not isinstance(result, dict) or any(
        not isinstance(name, str) or not isinstance(content, (str, int, float, bool, type(None)))
        for name, content in result.items()
    ):
        raise ValueError("Expected a flat attribute dictionary")
    attributes = {}
    for name, content in result.items():
        content = clean(str(content)) if content is not None else None
        if clean(name) and content is not None:
            attributes.setdefault(key(name), []).append(content)
    return attributes


def number(value, *, scale=1, maximum=None, integral=False):
    value = Decimal(value.strip())
    if not value.is_finite() or value < 0 or (maximum is not None and value > maximum):
        raise ValueError("Value outside allowed range")
    if integral:
        scaled = value * scale
        if scaled != scaled.to_integral_value() or scaled > 2**63 - 1:
            raise ValueError("Value cannot be stored as a SQLite integer")
        return int(scaled)
    return float(value)


def optional(row, field, parser, issues):
    value = row[field]
    if clean(value) is None:
        return None
    try:
        return parser(value)
    except (ValueError, SyntaxError, InvalidOperation, OverflowError, RecursionError):
        issues[field] += 1
        return None


def category_path(value):
    paths = json.loads(value)
    if not isinstance(paths, list) or any(not isinstance(path, str) for path in paths):
        raise ValueError("Expected a list of category strings")
    return [part.strip() for path in paths for part in path.split(">>") if part.strip()]


def normalize(platform, row, issues):
    def parse(field, parser):
        return optional(row, field, parser, issues)

    def price(field):
        return parse(field, lambda value: number(value, scale=100, integral=True))

    def rating(field):
        return parse(field, lambda value: number(value, maximum=5))

    if platform == "flipkart":
        attributes, notes = parse("product_specifications", parse_specs) or ({}, [])
        categories = parse("product_category_tree", category_path) or []
        colours = attributes.get("color", []) + attributes.get("colour", [])
        unique_colours = {key(value): value for value in colours}
        colour = next(iter(unique_colours.values())) if len(unique_colours) == 1 else None
        if len(unique_colours) > 1:
            issues["ambiguous_colour"] += 1
        return dict(
            source_id=clean(row["pid"]), source_record_id=clean(row["uniq_id"]),
            name=clean(row["product_name"]), brand=clean(row["brand"]),
            categories=categories, category_basis="source_category_tree" if categories else None,
            colour=colour, description=clean(row["description"]),
            attributes=attributes, notes=notes, retail_price_minor=price("retail_price"),
            price_minor=price("discounted_price"), rating=rating("product_rating"),
            overall_rating=rating("overall_rating"), rating_count=None,
            product_url=clean(row["product_url"]), image_url=None,
            observed_at=parse("crawl_timestamp", lambda value: datetime.strptime(
                value.strip(), "%Y-%m-%d %H:%M:%S %z"
            ).astimezone(timezone.utc).isoformat()),
        )
    source_id = parse("p_id", lambda value: str(number(value, integral=True)))
    name = clean(row["name"])
    title = key(name)
    categories = [
        category for category, pattern in MYNTRA_CATEGORIES.items()
        if re.search(pattern, title)
    ]
    if "Kurta Sets" in categories:
        categories.remove("Kurtas")
    if "T-Shirts" in categories and "Shirts" in categories:
        categories.remove("Shirts")
    if len(categories) != 1:
        categories = []
    return dict(
        source_id=source_id, source_record_id=source_id, name=name,
        brand=clean(row["brand"]), categories=categories,
        category_basis="inferred_from_title" if categories else None, colour=clean(row["colour"]),
        description=parse("description", strip_html),
        attributes=parse("p_attributes", parse_attributes) or {}, notes=[],
        retail_price_minor=None, price_minor=price("price"), rating=rating("avg_rating"),
        overall_rating=None,
        rating_count=parse("ratingCount", lambda value: number(value, integral=True)),
        product_url=None, image_url=clean(row["img"]), observed_at=None,
    )


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def records(path, platform):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        headers = reader.fieldnames
        if not headers or len(headers) != len(set(headers)):
            raise ValueError(f"{path.name}: missing or duplicate headers")
        missing = HEADERS[platform] - set(headers)
        if missing:
            raise ValueError(f"{path.name}: missing headers: {', '.join(sorted(missing))}")
        for record_number, row in enumerate(reader, start=1):
            if None in row or None in row.values():
                raise ValueError(f"{path.name}: invalid width at record {record_number}")
            yield record_number, {
                column: value for column, value in row.items()
                if column.strip() and not re.fullmatch(r"Unnamed: \d+", column)
            }
