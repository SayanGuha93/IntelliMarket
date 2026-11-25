# Dashboard DAX

These definitions are implemented in the TMDL model. Create the model columns in the order below if reconstructing in Desktop.

## Calculated columns

### fact_product

~~~dax
listing = fact_product[product_name] & " (" & fact_product[marketplace] & ":" & fact_product[source_product_id] & ")"

listing_compact = LEFT(fact_product[product_name], 38) & IF(LEN(fact_product[product_name]) > 38, "…", "") & " · " & IF(fact_product[marketplace] = "flipkart", "FK ", "MY ") & fact_product[source_product_id]

scatter_bin = VAR Price = fact_product[recorded_price] VAR Stars = fact_product[rating] RETURN IF(NOT ISBLANK(Price) && NOT ISBLANK(Stars), INT(LOG10(1 + Price) * 5) & "|" & INT(Stars * 5))

discount_band_order = IF(ISBLANK(fact_product[discount_fraction]), BLANK(), IF(fact_product[discount_fraction] = 0, 0, MIN(4, 1 + INT(fact_product[discount_fraction] * 4))))

discount_band = IF(ISBLANK(fact_product[discount_band_order]), BLANK(), SWITCH(fact_product[discount_band_order], 0, "0%", 1, ">0% to <25%", 2, "25% to <50%", 3, "50% to <75%", 4, "75% to 100%"))

rating_band_order = IF(ISBLANK(fact_product[rating]), BLANK(), INT(fact_product[rating]))

rating_band = IF(ISBLANK(fact_product[rating_band_order]), BLANK(), SWITCH(fact_product[rating_band_order], 0, "0 to <1", 1, "1 to <2", 2, "2 to <3", 3, "3 to <4", 4, "4 to <5", 5, "5"))

~~~

### dim_category

~~~dax
comparison_category = VAR Segments = SUBSTITUTE(dim_category[category_path], " > ", "|")
RETURN SWITCH(TRUE(),
    PATHCONTAINS(Segments, "Kurta Sets"), "Kurta Sets",
    PATHCONTAINS(Segments, "Kurtas") || PATHCONTAINS(Segments, "Kurtas & Kurtis"), "Kurtas",
    PATHCONTAINS(Segments, "T-Shirts"), "T-Shirts",
    PATHCONTAINS(Segments, "Shirts"), "Shirts",
    PATHCONTAINS(Segments, "Jeans"), "Jeans",
    PATHCONTAINS(Segments, "Sarees"), "Sarees",
    PATHCONTAINS(Segments, "Jackets"), "Jackets",
    PATHCONTAINS(Segments, "Trousers"), "Trousers",
    PATHCONTAINS(Segments, "Dresses"), "Dresses",
    PATHCONTAINS(Segments, "Tops"), "Tops",
    BLANK())

category_display = IF(LEN(TRIM(dim_category[top_category])) = 0, "Unknown category", dim_category[top_category])

~~~

## Measures

Create on fact_product.

~~~dax
Product Count = COUNTROWS(fact_product)

Flipkart Products = CALCULATE([Product Count], KEEPFILTERS(dim_marketplace[marketplace] = "flipkart"))

Myntra Products = CALCULATE([Product Count], KEEPFILTERS(dim_marketplace[marketplace] = "myntra"))

Known Brands = CALCULATE(DISTINCTCOUNT(fact_product[brand_id]), KEEPFILTERS(fact_product[brand_id] <> 0))

Categories Recorded = CALCULATE(DISTINCTCOUNT(fact_product[category_id]), KEEPFILTERS(fact_product[category_id] <> 0))

Marketplace Share = DIVIDE([Product Count], CALCULATE([Product Count], REMOVEFILTERS(dim_marketplace)))

Priced Products = COUNT(fact_product[recorded_price])

Price Coverage = DIVIDE([Priced Products], [Product Count])

Average Recorded Price = AVERAGE(fact_product[recorded_price])

Median Recorded Price = MEDIAN(fact_product[recorded_price])

Discount Eligible Products = COUNT(fact_product[discount_fraction])

Discounted Products = CALCULATE([Product Count], KEEPFILTERS(fact_product[discount_fraction] > 0))

Average Valid Discount = AVERAGE(fact_product[discount_fraction])

Recorded Retail Price = SELECTEDVALUE(fact_product[retail_price])

Recorded Listing Price = SELECTEDVALUE(fact_product[recorded_price])

Listing Discount Amount = SELECTEDVALUE(fact_product[discount_amount])

Rated Products = SUM(fact_product[has_rating])

Rating Coverage = DIVIDE([Rated Products], [Product Count])

Average Recorded Rating = AVERAGE(fact_product[rating])

Products With Rating Count = SUM(fact_product[has_rating_count])

Reported Rating Count = SUM(fact_product[rating_count])

Missing Rating = [Product Count] - [Rated Products]

Missing Attributes = SUM(fact_product[missing_attributes])

Category Coverage = DIVIDE([Product Count] - SUM(fact_product[missing_category]), [Product Count])

Brand Coverage = DIVIDE([Product Count] - SUM(fact_product[missing_brand]), [Product Count])

Attribute Coverage = DIVIDE([Product Count] - [Missing Attributes], [Product Count])

Shared Category = VAR Label = SELECTEDVALUE(dim_category[comparison_category])
VAR Flipkart = CALCULATE([Priced Products], REMOVEFILTERS(dim_marketplace), dim_marketplace[marketplace] = "flipkart")
VAR Myntra = CALCULATE([Priced Products], REMOVEFILTERS(dim_marketplace), dim_marketplace[marketplace] = "myntra")
RETURN IF(NOT ISBLANK(Label) && Flipkart > 0 && Myntra > 0, 1, 0)

Ranking Rating = IF(HASONEVALUE(fact_product[product_id]) && SELECTEDVALUE(fact_product[rating_count]) >= 10, SELECTEDVALUE(fact_product[rating]))

Ranking Rating Count = IF(NOT ISBLANK([Ranking Rating]), SELECTEDVALUE(fact_product[rating_count]))

Comparable Priced Listings = IF([Shared Category] = 1, [Priced Products])

Comparable Median Price = IF([Shared Category] = 1, [Median Recorded Price])

Comparable Average Price = IF([Shared Category] = 1, [Average Recorded Price])

Log Recorded Price = AVERAGEX(FILTER(fact_product, NOT ISBLANK(fact_product[recorded_price])), LOG10(1 + fact_product[recorded_price]))

Minimum Recorded Price = MIN(fact_product[recorded_price])

Maximum Recorded Price = MAX(fact_product[recorded_price])

Flipkart Median Recorded Price = CALCULATE([Median Recorded Price], KEEPFILTERS(dim_marketplace[marketplace] = "flipkart"))

Myntra Median Recorded Price = CALCULATE([Median Recorded Price], KEEPFILTERS(dim_marketplace[marketplace] = "myntra"))

~~~

| Format | Measures |
|---|---|
| #,0 | Product Count, Flipkart Products, Myntra Products, Known Brands, Categories Recorded, Priced Products, Discount Eligible Products, Discounted Products, Rated Products, Products With Rating Count, Reported Rating Count, Missing Rating, Missing Attributes, Shared Category, Ranking Rating Count, Comparable Priced Listings |
| #,0.00 | Average Recorded Price, Median Recorded Price, Recorded Retail Price, Recorded Listing Price, Listing Discount Amount, Average Recorded Rating, Ranking Rating, Comparable Median Price, Comparable Average Price, Log Recorded Price, Minimum Recorded Price, Maximum Recorded Price, Flipkart Median Recorded Price, Myntra Median Recorded Price |
| 0.0% | Marketplace Share, Price Coverage, Average Valid Discount, Rating Coverage, Category Coverage, Brand Coverage, Attribute Coverage |

## Interpretation and independently checked baseline

- Average recorded price is 2,388.65 and median is 1,198 across recorded values. Flipkart median is 550 and Myntra median is 2,217. These are catalog values with different source price definitions and unspecified currency.
- 19,920 Flipkart listings have calculable discount pairs. Average Valid Discount averages these listing percentages, including 2,287 equal-price pairs. The baseline is 40.53%. Discounted Products counts 17,633 strictly positive values. Myntra provides no comparable retail/discount pair.
- The catalog has 4,320 distinct known brand keys. Slicing marketplaces can count the same brand in both slices.
- There are 8,383 rated listings with a mean of 4.0363. The ranking uses a **minimum of 10 source-reported ratings** and only includes listings with a recorded rating. There are 4,853 eligible listings, all on Myntra. Flipkart lacks rating counts, so its rated products still appear in ratings and coverage charts.
- Comparison mapping matches entire category hierarchy segments. Kurtas & Kurtis maps to Kurtas. Rules pick the first documented match. The matrix requires recorded prices on both platforms within the other active filters. Nine categories qualify before filtering. They are comparable category groupings of different assortments. Myntra categories are inferred where present.
- Ratings and prices absent from the source remain blank. Discounts and ratings use separate ordered bands. Known brand, category and coverage counts describe this catalog snapshot.
