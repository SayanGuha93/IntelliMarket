# Proposed DAX measures

Create each expression separately on fact_product. Format share, coverage and discount percentage as percentages. Use decimals without a currency symbol for price measures.

~~~dax
Product Count = COUNTROWS(fact_product)
Marketplace Share =
    DIVIDE([Product Count], CALCULATE([Product Count], REMOVEFILTERS(dim_marketplace)))
Category Share =
    DIVIDE([Product Count], CALCULATE([Product Count], REMOVEFILTERS(dim_category)))
Brand Share =
    DIVIDE([Product Count], CALCULATE([Product Count], REMOVEFILTERS(dim_brand)))
Priced Products = COUNT(fact_product[recorded_price])
Price Coverage = DIVIDE([Priced Products], [Product Count])
Median Recorded Price = MEDIAN(fact_product[recorded_price])
Average Retail Price = AVERAGE(fact_product[retail_price])
Average Discounted Price = AVERAGE(fact_product[discounted_price])
Discount Eligible Products = COUNT(fact_product[discount_fraction])
Products With Positive Discount =
    CALCULATE([Product Count], KEEPFILTERS(fact_product[discount_fraction] > 0))
Average Discount Amount = AVERAGE(fact_product[discount_amount])
Average Discount Percentage = AVERAGE(fact_product[discount_fraction])
Rated Products = SUM(fact_product[has_rating])
Rating Coverage = DIVIDE([Rated Products], [Product Count])
Average Product Rating = AVERAGE(fact_product[rating])
Average Overall Rating = AVERAGE(fact_product[overall_rating])
Products With Rating Count = SUM(fact_product[has_rating_count])
Reported Rating Count = SUM(fact_product[rating_count])
Products Missing Brand = SUM(fact_product[missing_brand])
Products Missing Category = SUM(fact_product[missing_category])
Products Missing Attributes = SUM(fact_product[missing_attributes])
~~~

Average Discount Percentage weights each eligible listing equally and includes recorded equal-price pairs. An empty eligibility set yields a blank average. Reported Rating Count sums available source counts and should travel with its coverage. Marketplace Share uses the full marketplace set within the other current dimension filters.
