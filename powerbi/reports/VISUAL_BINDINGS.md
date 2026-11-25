# Dashboard visual bindings

All pages have a heading, page navigation and a historical-data footer. Use the visual JSON positions for placement.

## Marketplace Overview

| Visual title | Type | Field wells |
|---|---|---|
| Marketplace | slicer | Values — dim_marketplace.marketplace_name |
| Top category | slicer | Values — dim_category.category_display |
| Brand | slicer | Values — dim_brand.brand_name |
| Catalog listings | cardVisual | Data — fact_product.Product Count |
| Flipkart listings | cardVisual | Data — fact_product.Flipkart Products |
| Myntra listings | cardVisual | Data — fact_product.Myntra Products |
| Known brands | cardVisual | Data — fact_product.Known Brands |
| Marketplace distribution | donutChart | Category — dim_marketplace.marketplace_name<br>Tooltips — fact_product.Marketplace Share<br>Y — fact_product.Product Count |
| Top 8 categories by listings | clusteredBarChart | Category — dim_category.category_display<br>Y — fact_product.Product Count |
| Top 8 known brands by listings | clusteredBarChart | Category — dim_brand.brand_name<br>Y — fact_product.Product Count |
| Category and marketplace distribution | pivotTable | Rows — dim_category.category_display<br>Columns — dim_marketplace.marketplace_name<br>Values — fact_product.Product Count |

## Price and Discount Analytics

| Visual title | Type | Field wells |
|---|---|---|
| Marketplace | slicer | Values — dim_marketplace.marketplace_name |
| Top category | slicer | Values — dim_category.category_display |
| Recorded price band | slicer | Values — dim_price_band.price_band |
| Average recorded price | cardVisual | Data — fact_product.Average Recorded Price |
| Median recorded price | cardVisual | Data — fact_product.Median Recorded Price |
| Average valid Flipkart discount | cardVisual | Data — fact_product.Average Valid Discount |
| Listings with positive discount | cardVisual | Data — fact_product.Discounted Products |
| Product price distribution | clusteredColumnChart | Category — dim_price_band.price_band<br>Series — dim_marketplace.marketplace_name<br>Y — fact_product.Priced Products |
| Price bands and median recorded price | tableEx | Values — dim_price_band.price_band, fact_product.Product Count, fact_product.Flipkart Median Recorded Price, fact_product.Myntra Median Recorded Price |
| Flipkart discount distribution | clusteredColumnChart | Category — fact_product.discount_band<br>Y — fact_product.Discount Eligible Products |
| Recorded price by category and marketplace | clusteredBarChart | Category — dim_category.category_display<br>Y — fact_product.Median Recorded Price<br>Series — dim_marketplace.marketplace_name<br>Tooltips — fact_product.Priced Products |
| Top 20 Flipkart discounts | tableEx | Values — fact_product.listing_compact, fact_product.Recorded Retail Price, fact_product.Recorded Listing Price, fact_product.Listing Discount Amount, fact_product.Average Valid Discount |

## Flipkart vs Myntra

| Visual title | Type | Field wells |
|---|---|---|
| Comparison category | slicer | Values — dim_category.comparison_category |
| Recorded price band | slicer | Values — dim_price_band.price_band |
| Top category | slicer | Values — dim_category.category_display |
| Product listings by marketplace | clusteredBarChart | Category — dim_marketplace.marketplace_name<br>Y — fact_product.Product Count |
| Recorded price distribution by marketplace | clusteredColumnChart | Category — dim_price_band.price_band<br>Series — dim_marketplace.marketplace_name<br>Y — fact_product.Priced Products |
| Category and brand coverage | tableEx | Values — dim_marketplace.marketplace_name, fact_product.Categories Recorded, fact_product.Category Coverage, fact_product.Known Brands, fact_product.Brand Coverage |
| Mapped categories with recorded prices on both marketplaces | pivotTable | Rows — dim_category.comparison_category<br>Columns — dim_marketplace.marketplace_name<br>Values — fact_product.Comparable Priced Listings, fact_product.Comparable Median Price, fact_product.Comparable Average Price |
| Data completeness by marketplace | tableEx | Values — dim_marketplace.marketplace_name, fact_product.Price Coverage, fact_product.Category Coverage, fact_product.Brand Coverage, fact_product.Rating Coverage, fact_product.Attribute Coverage |

## Product and Rating Analytics

| Visual title | Type | Field wells |
|---|---|---|
| Marketplace | slicer | Values — dim_marketplace.marketplace_name |
| Top category | slicer | Values — dim_category.category_display |
| Brand | slicer | Values — dim_brand.brand_name |
| Rated listings | cardVisual | Data — fact_product.Rated Products |
| Rating coverage | cardVisual | Data — fact_product.Rating Coverage |
| Average recorded rating | cardVisual | Data — fact_product.Average Recorded Rating |
| Listings with a rating count | cardVisual | Data — fact_product.Products With Rating Count |
| Recorded rating distribution | clusteredColumnChart | Category — fact_product.rating_band<br>Series — dim_marketplace.marketplace_name<br>Y — fact_product.Rated Products |
| Rating and price density by marketplace | scatterChart | Category — fact_product.scatter_bin<br>X — fact_product.Log Recorded Price<br>Y — fact_product.Average Recorded Rating<br>Series — dim_marketplace.marketplace_name<br>Size — fact_product.Priced Products<br>Tooltips — fact_product.Minimum Recorded Price, fact_product.Maximum Recorded Price |
| Missing rating and attributes | clusteredColumnChart | Category — dim_marketplace.marketplace_name<br>Y — fact_product.Missing Rating, fact_product.Missing Attributes |
| Brand ratings and sample sizes | tableEx | Values — dim_brand.brand_name, fact_product.Average Recorded Rating, fact_product.Rated Products, fact_product.Product Count, fact_product.Rating Coverage |
| Highest ratings with at least 10 reported ratings | tableEx | Values — fact_product.listing_compact, dim_marketplace.marketplace_name, fact_product.Ranking Rating, fact_product.Ranking Rating Count, fact_product.Recorded Listing Price |
