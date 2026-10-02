import re

from data_sources.product_matcher import (
    get_tokens,
    jaccard_similarity,
    sequence_similarity
)
from ml.semantic_matcher import semantic_similarity


BRAND_ALIASES = {
    "wd": "western digital",
    "western digital": "western digital",
    "sandisk": "sandisk",
    "samsung": "samsung",
    "apple": "apple",
    "acer": "acer",
    "sony": "sony",
    "hp": "hp",
    "dell": "dell",
    "lenovo": "lenovo"
}


BASE_WEIGHTS = {
    "name": 0.25,
    "semantic": 0.30,
    "brand": 0.15,
    "model": 0.20,
    "specification": 0.10
}


def normalize_brand(brand):
    if not brand:
        return None

    normalized = brand.lower().strip()

    if normalized in {"unknown", "n/a", "na", "none", ""}:
        return None

    return BRAND_ALIASES.get(normalized, normalized)


def extract_brand_from_name(name):
    normalized_name = name.lower()

    for alias, canonical_brand in BRAND_ALIASES.items():
        pattern = rf"\b{re.escape(alias)}\b"

        if re.search(pattern, normalized_name):
            return canonical_brand

    return None


def get_effective_brand(product):
    metadata_brand = normalize_brand(product.get("brand"))

    if metadata_brand:
        return metadata_brand

    return extract_brand_from_name(
        product.get("product_name", "")
    )


def extract_specifications(name):
    normalized = name.lower()

    specifications = set(
        re.findall(
            r"\b\d+(?:\.\d+)?\s?(?:tb|gb|mb|inch|in|hz|w|mm|cm|kg|g)\b",
            normalized
        )
    )

    return specifications


def specification_score(name1, name2):
    specs1 = extract_specifications(name1)
    specs2 = extract_specifications(name2)

    if not specs1 and not specs2:
        return None

    if not specs1 or not specs2:
        return None

    return len(specs1.intersection(specs2)) / max(
        len(specs1.union(specs2)),
        1
    )


def brand_score(product1, product2):
    brand1 = get_effective_brand(product1)
    brand2 = get_effective_brand(product2)

    if not brand1 or not brand2:
        return None

    if brand1 == brand2:
        return 1

    return 0


def model_score(model1, model2):
    if not model1 or not model2:
        return None

    model1 = model1.lower().strip()
    model2 = model2.lower().strip()

    if model1 == model2:
        return 1

    return 0


def name_score(name1, name2):
    tokens1 = get_tokens(name1)
    tokens2 = get_tokens(name2)

    if not tokens1 or not tokens2:
        return 0

    jaccard = jaccard_similarity(name1, name2)
    sequence = sequence_similarity(name1, name2)

    return (jaccard * 0.7) + (sequence * 0.3)


def hybrid_similarity(product1, product2):
    name1 = product1["product_name"]
    name2 = product2["product_name"]

    scores = {
        "name": name_score(name1, name2),
        "semantic": semantic_similarity(name1, name2),
        "brand": brand_score(product1, product2),
        "model": model_score(
            product1.get("model"),
            product2.get("model")
        ),
        "specification": specification_score(
            name1,
            name2
        )
    }

    available_scores = {
        key: value
        for key, value in scores.items()
        if value is not None
    }

    total_weight = sum(
        BASE_WEIGHTS[key]
        for key in available_scores
    )

    normalized_weights = {
        key: BASE_WEIGHTS[key] / total_weight
        for key in available_scores
    }

    final_score = sum(
        available_scores[key] * normalized_weights[key]
        for key in available_scores
    )

    conflicting_brand = scores["brand"] == 0
    conflicting_model = scores["model"] == 0
    conflicting_specification = (
        scores["specification"] == 0
    )

    if (
        conflicting_brand
        or conflicting_model
        or conflicting_specification
    ):
        decision = "NO_MATCH"
    elif final_score >= 0.75:
        decision = "MATCH"
    else:
        decision = "NO_MATCH"

    return {
        "name_score": scores["name"],
        "semantic_score": scores["semantic"],
        "brand_score": scores["brand"],
        "model_score": scores["model"],
        "specification_score": scores["specification"],
        "final_score": final_score,
        "decision": decision,
        "weights_used": normalized_weights
    }