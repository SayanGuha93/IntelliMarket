"""Turn catalog evidence into bounded, deduplicated semantic chunks."""

import json
import re


URL = re.compile(
    r"(?:https?://|ftp://|www\.)[^\s<>\"']+|\b(?:flipkart\.com|myntra\.com)\b", re.I
)
TIMESTAMP = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\s*(?:Z|[+-]\d{2}:?\d{2}))?)?\b")
PRICE = re.compile(
    r"(?:₹|\$|£|€|\b(?:Rs\.?|INR|USD|GBP|EUR)\s*)\s*\d[\d,.]*"
    r"|\b(?:priced? at|(?:sale |retail |discounted )?price\s*[:=]|MRP\s*[:=]?)\s*\d[\d,.]*",
    re.I,
)
RATING = re.compile(
    r"\b(?:product |overall |average )?ratings?(?:\s+of|\s*:)?\s*\d(?:\.\d+)?(?:\s*(?:/|out of)\s*5)?"
    r"|\b\d+(?:\.\d+)?\s*(?:stars?\b|ratings?\b|(?:/|out of)\s*5\b)",
    re.I,
)
PROMOTIONAL = re.compile(
    r"\b(?:free shipping|cash on delivery|buy online|shop now|order now|best price|"
    r"lowest price|view more|check price|available at flipkart\.com|only genuine products|"
    r"\d+\s+days?\s+replacement(?: guarantee)?|buy [^.!?]{1,240} for only)\b", re.I,
)
IGNORED_ATTRIBUTES = re.compile(
    r"\b(?:ratings?|reviews?|prices?|mrp|discount|offers?|warranty|installation|"
    r"seller|shipping|return policy|url|timestamp|"
    r"barcode|sku|gtin|upc|ean|isbn|id|model number|style code|part number)\b", re.I,
)


def semantic_text(value, ids=()):
    if not value:
        return ""
    value = PRICE.sub(" ", value)
    value = RATING.sub(" ", value)
    value = TIMESTAMP.sub(" ", value)
    value = PROMOTIONAL.sub(" ", value)
    value = URL.sub(" ", value)
    for source_id in ids:
        if source_id:
            value = re.sub(rf"(?<!\w){re.escape(source_id)}(?:\.0\b)?(?!\w)", " ", value, flags=re.I)
    return " ".join(value.split()).strip(" ,;:-.")


def product_document(product, source_ids=()):
    ids = (product["source_id"], *source_ids)
    title = semantic_text(product["name"], ids)
    sections = []
    seen = {title.casefold()}

    def add(label, value):
        value = semantic_text(value, ids)
        if value and value.casefold() not in seen:
            sections.append(f"{label}: {value}")
            seen.add(value.casefold())

    add("Brand", product["brand"])
    categories = [
        category for category in json.loads(product["category_path"])
        if not category.casefold().startswith(product["name"].casefold())
    ]
    add("Category", " > ".join(categories))
    add("Colour", product["colour"])
    for label, values in json.loads(product["attributes"]).items():
        if not IGNORED_ATTRIBUTES.search(label):
            add(label.capitalize(), "; ".join(dict.fromkeys(values)))
    for note in json.loads(product["notes"]):
        if not IGNORED_ATTRIBUTES.search(note):
            add("Specification", note)
    add("Description", product["description"])
    return title, sections


def chunk_document(tokenizer, title, sections, max_tokens):
    """Use tokenizer offsets to split long sections without altering their text."""
    prefix = f"Product: {title}" if title else ""

    def size(text):
        return len(tokenizer.encode(text, add_special_tokens=False, verbose=False))

    def combine(first, second):
        return f"{first}\n{second}" if first and second else first or second

    # Keep room for section content even when the title itself is unusually long.
    if size(prefix) > max_tokens // 3:
        offsets = tokenizer(prefix, add_special_tokens=False, return_offsets_mapping=True,
                            verbose=False)["offset_mapping"]
        prefix = prefix[:offsets[max_tokens // 3 - 1][1]]
    chunks = []
    current = prefix
    for section in sections:
        if size(combine(current, section)) <= max_tokens:
            current = combine(current, section)
            continue
        if current != prefix:
            chunks.append(current)
            current = prefix
        remaining = section
        while remaining and size(combine(prefix, remaining)) > max_tokens:
            offsets = tokenizer(remaining, add_special_tokens=False, return_offsets_mapping=True,
                                verbose=False)["offset_mapping"]
            take = min(len(offsets), max_tokens - size(prefix) - 2)
            while size(combine(prefix, remaining[:offsets[take - 1][1]])) > max_tokens:
                take -= 1
            end = offsets[take - 1][1]
            chunks.append(combine(prefix, remaining[:end]))
            remaining = remaining[end:].lstrip()
        if remaining:
            current = combine(prefix, remaining)
    if current and (current != prefix or not chunks):
        chunks.append(current)
    return list(dict.fromkeys(chunks))
