import re
from difflib import SequenceMatcher

STOP_WORDS = {
    "the", "and", "with", "for", "from", "new", "original",
    "edition", "series", "version", "inch", "inches"
}

def normalize_name(name):
    name = name.lower()
    name = re.sub(r"[^a-z0-9\s]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name

def get_tokens(name):
    normalized = normalize_name(name)
    return {
        token
        for token in normalized.split()
        if token not in STOP_WORDS
    }

def token_coverage(name1, name2):
    tokens1 = get_tokens(name1)
    tokens2 = get_tokens(name2)

    if not tokens1 or not tokens2:
        return 0

    common = tokens1.intersection(tokens2)
    shorter_count = min(len(tokens1), len(tokens2))

    return len(common) / shorter_count

def jaccard_similarity(name1, name2):
    tokens1 = get_tokens(name1)
    tokens2 = get_tokens(name2)

    if not tokens1 or not tokens2:
        return 0

    return len(tokens1.intersection(tokens2)) / len(tokens1.union(tokens2))

def sequence_similarity(name1, name2):
    return SequenceMatcher(
        None,
        normalize_name(name1),
        normalize_name(name2)
    ).ratio()

def similarity(name1, name2):
    tokens1 = get_tokens(name1)
    tokens2 = get_tokens(name2)

    common_tokens = tokens1.intersection(tokens2)

    if len(common_tokens) >= 4:
        coverage = token_coverage(name1, name2)

        if coverage >= 0.8:
            return 1.0

    token_score = jaccard_similarity(name1, name2)
    sequence_score = sequence_similarity(name1, name2)

    if len(common_tokens) < 2:
        return 0

    return (token_score * 0.7) + (sequence_score * 0.3)

def find_matching_product(products, product_name, threshold=0.65):
    best_product = None
    best_score = 0

    for product in products:
        score = similarity(product["product_name"], product_name)

        if score > best_score:
            best_score = score
            best_product = product

    if best_score >= threshold:
        return best_product

    return None