from data_sources.product_matcher import similarity
from ml.semantic_matcher import semantic_similarity
from ml.hybrid_matcher import hybrid_similarity

pairs = [
    (
        {
            "product_name": "WD 2TB Elements Portable External Hard Drive",
            "brand": "Western Digital",
            "model": "WDBU6Y0020BBK"
        },
        {
            "product_name": "Western Digital Elements 2TB Portable Hard Drive",
            "brand": "Western Digital",
            "model": "WDBU6Y0020BBK"
        },
        True
    ),
    (
        {
            "product_name": "WD 2TB Elements Portable External Hard Drive",
            "brand": "Western Digital",
            "model": "WDBU6Y0020BBK"
        },
        {
            "product_name": "WD Elements Portable External Hard Drive 4TB",
            "brand": "Western Digital",
            "model": "WDBU6Y0040BBK"
        },
        False
    ),
    (
        {
            "product_name": "SanDisk SSD PLUS 1TB Internal SSD",
            "brand": "SanDisk",
            "model": "SDSSDA-1T00"
        },
        {
            "product_name": "SanDisk 1TB SSD PLUS SATA III Internal SSD",
            "brand": "SanDisk",
            "model": "SDSSDA-1T00"
        },
        True
    ),
    (
        {
            "product_name": "Samsung Galaxy Phone 128GB",
            "brand": "Samsung",
            "model": "SM-A123"
        },
        {
            "product_name": "Samsung Galaxy Phone 256GB",
            "brand": "Samsung",
            "model": "SM-A124"
        },
        False
    ),
    (
        {
            "product_name": "Mens Casual Premium Slim Fit T-Shirts",
            "brand": "Unknown",
            "model": None
        },
        {
            "product_name": "Mens Casual Slim Fit",
            "brand": "Unknown",
            "model": None
        },
        False
    ),
    (
        {
            "product_name": "Apple MacBook Air 13 inch 8GB 256GB",
            "brand": "Apple",
            "model": "A2337"
        },
        {
            "product_name": "Apple MacBook Air 13 inch 8GB 256GB",
            "brand": "Apple",
            "model": "A2337"
        },
        True
    )
]

rule_correct = 0
semantic_correct = 0
hybrid_correct = 0

for product1, product2, expected in pairs:
    rule_score = similarity(
        product1["product_name"],
        product2["product_name"]
    )

    semantic_score = semantic_similarity(
        product1["product_name"],
        product2["product_name"]
    )

    hybrid_result = hybrid_similarity(product1, product2)
    hybrid_score = hybrid_result["final_score"]

    rule_match = rule_score >= 0.65
    semantic_match = semantic_score >= 0.85
    hybrid_match = hybrid_score >= 0.75

    if rule_match == expected:
        rule_correct += 1

    if semantic_match == expected:
        semantic_correct += 1

    if hybrid_match == expected:
        hybrid_correct += 1

    print()
    print("=" * 70)
    print(product1["product_name"])
    print(product2["product_name"])
    print("Expected:", expected)
    print("Rule Score:", round(rule_score, 4))
    print("Rule Match:", rule_match)
    print("Semantic Score:", round(semantic_score, 4))
    print("Semantic Match:", semantic_match)
    print("Hybrid Score:", round(hybrid_score, 4))
    print("Hybrid Match:", hybrid_match)

total = len(pairs)

print()
print("=" * 70)
print("MATCHER EVALUATION")
print("=" * 70)
print("Total Test Pairs:", total)
print("Rule-Based Accuracy:", round(rule_correct / total * 100, 2), "%")
print("MiniLM Accuracy:", round(semantic_correct / total * 100, 2), "%")
print("Hybrid Accuracy:", round(hybrid_correct / total * 100, 2), "%")