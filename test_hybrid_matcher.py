from ml.hybrid_matcher import hybrid_similarity

pairs = [
    (
        "Same brand + same model",
        {
            "product_name": "WD 2TB Elements Portable External Hard Drive",
            "brand": "Western Digital",
            "model": "WDBU6Y0020BBK"
        },
        {
            "product_name": "Western Digital Elements 2TB Portable Hard Drive",
            "brand": "Western Digital",
            "model": "WDBU6Y0020BBK"
        }
    ),
    (
        "Brand missing + model present",
        {
            "product_name": "WD 2TB Elements Portable External Hard Drive",
            "brand": None,
            "model": "WDBU6Y0020BBK"
        },
        {
            "product_name": "Western Digital Elements 2TB Portable Hard Drive",
            "brand": "Western Digital",
            "model": "WDBU6Y0020BBK"
        }
    ),
    (
        "Brand present + model missing",
        {
            "product_name": "WD 2TB Elements Portable External Hard Drive",
            "brand": "Western Digital",
            "model": None
        },
        {
            "product_name": "Western Digital Elements 2TB Portable Hard Drive",
            "brand": "Western Digital",
            "model": None
        }
    ),
    (
        "Brand missing + model missing",
        {
            "product_name": "WD 2TB Elements Portable External Hard Drive",
            "brand": None,
            "model": None
        },
        {
            "product_name": "Western Digital Elements 2TB Portable Hard Drive",
            "brand": "Western Digital",
            "model": None
        }
    ),
    (
        "Different brand",
        {
            "product_name": "WD 2TB Elements Portable External Hard Drive",
            "brand": "Western Digital",
            "model": "WDBU6Y0020BBK"
        },
        {
            "product_name": "SanDisk 2TB Portable External Hard Drive",
            "brand": "SanDisk",
            "model": "SDSSDE61-2T00"
        }
    ),
    (
        "Different model",
        {
            "product_name": "WD 2TB Elements Portable External Hard Drive",
            "brand": "Western Digital",
            "model": "WDBU6Y0020BBK"
        },
        {
            "product_name": "WD 2TB Elements Portable External Hard Drive",
            "brand": "Western Digital",
            "model": "WDBU6Y0040BBK"
        }
    ),
    (
        "Different specification",
        {
            "product_name": "Samsung Galaxy Phone 128GB",
            "brand": "Samsung",
            "model": "SM-A123"
        },
        {
            "product_name": "Samsung Galaxy Phone 256GB",
            "brand": "Samsung",
            "model": "SM-A124"
        }
    ),
    (
        "No metadata",
        {
            "product_name": "Mens Casual Premium Slim Fit T-Shirts",
            "brand": None,
            "model": None
        },
        {
            "product_name": "Mens Casual Slim Fit",
            "brand": None,
            "model": None
        }
    )
]

for name, product1, product2 in pairs:
    result = hybrid_similarity(product1, product2)

    print()
    print("=" * 70)
    print(name)
    print("Product 1:", product1["product_name"])
    print("Product 2:", product2["product_name"])
    print("Brand Score:", result["brand_score"])
    print("Model Score:", result["model_score"])
    print("Specification Score:", result["specification_score"])
    print("Final Score:", round(result["final_score"], 4))
    print("Decision:", result["decision"])