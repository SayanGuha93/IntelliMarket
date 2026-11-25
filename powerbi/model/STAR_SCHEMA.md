# Star schema and data dictionary

Grain is one distinct catalog product listing per marketplace and source product ID. The primary key is the catalog product_id. Listings from different marketplaces remain distinct. Build four active one-to-many relationships with cross-filter direction Single from dimension to fact.

| One side | Many side | Rows |
|---|---|---:|
| dim_marketplace.marketplace | fact_product.marketplace | 2 dimension rows |
| dim_brand.brand_id | fact_product.brand_id | 4,321 dimension rows |
| dim_category.category_id | fact_product.category_id | 6,475 dimension rows |
| dim_price_band.price_band_id | fact_product.price_band_id | 6 dimension rows |

fact_product has 34,220 rows. source_lineage has 34,330 rows and stays disconnected from the star. Use it for audit or a deliberately filtered drill-through in a later phase. Its product_id can repeat and is blank for excluded source rows. The catalog categories table is a search index with multiple entries per product. It is not imported. Each listing has one category path dimension row (or Unrecorded), allowing additive category counts.

## Fact columns

| Columns | Type and source |
|---|---|
| product_id | Whole number. SQLite products.id, unique within the snapshot. |
| marketplace, source_product_id, product_name | Text. products.platform, source_id and name. Keep source ID as text. |
| brand_id, category_id, price_band_id | Whole numbers. Foreign keys with zero reserved for Unrecorded. |
| colour | Nullable text. Normalised catalog colour. |
| recorded_price_field | Text. Flipkart discounted_price or Myntra price. |
| recorded_price, retail_price, discounted_price | Nullable fixed decimal. Catalog stored values divided by 100. Retail and discounted fields are Flipkart-specific in this snapshot. Display as numeric values with unspecified currency. |
| discount_amount, discount_fraction | Nullable fixed decimal amount and decimal ratio. Eligible when the field denotes a Flipkart discounted price, retail is positive, and discounted is between zero and retail. Equal prices yield zero. Percentage format displays the ratio multiplied by 100. |
| rating, overall_rating | Nullable decimal on the source 0–5 scale. Keep the two source measures separate. |
| rating_count | Nullable whole number. Source-reported count. Flipkart has no counts. |
| has_rating, has_overall_rating, has_rating_count | Whole-number 1/0 availability flags, including recorded zeros. |
| missing_recorded_price, missing_retail_price, missing_brand, missing_category, missing_attributes, missing_colour, missing_observation_date | Whole-number 1/0 flags. Missing attributes means an empty catalog attribute object. Missing retail includes marketplaces where it is unavailable by design. |
| has_conflicts | Whole-number 1/0. Catalog conflicts object has at least one entry. |
| observed_at, product_url | Nullable text. Source crawl timestamp and listing URL. Timestamp supports provenance. |
| attributes_json | Text. Canonical products.attributes, with arrays of values. Keep unexpanded in the fact to preserve grain. |

## Dimension and lineage columns

- dim_marketplace contains text marketplace and marketplace_name.
- dim_brand contains whole-number brand_id, normalised text brand_key and display brand_name. Blank keys or missing labels map to Unrecorded. A normalised shared brand label does not imply matching products.
- dim_category contains whole-number category_id and category_depth, and text category_path, top_category, leaf_category and category_basis. Flipkart paths come from the source category tree. Available Myntra paths are title-inferred. Use basis and marketplace to explain coverage and taxonomy differences.
- dim_price_band contains whole-number price_band_id and text price_band. Bands use the recorded price and boundaries 500, 1,000, 1,500 and 3,000. Each boundary starts the next band. Sort the label by price_band_id.
- source_lineage contains text source_file, marketplace, source_record_id, status and reason. Whole-number record_number is the catalog's source-row reference. Whole-number product_id and duplicate_of_record_number are nullable. The unique source key is marketplace plus record_number. Status values are accepted, duplicate and excluded.

## Reconciliation

There are 19,998 Flipkart products and 14,222 Myntra products. The independent SQLite checks compare product and lineage identity sets, dimension coverage, category and band assignments, price semantics including both zero and blank discounts, exact stored prices, rating availability and flags. Lineage includes 34,267 accepted, 44 duplicate and 19 excluded rows.

| Coverage | Flipkart | Myntra |
|---|---:|---:|
| Recorded price | 19,920 | 14,222 |
| Discount calculable | 19,920 | 0 |
| Strictly positive discounts | 17,633 | 0 |
| Product rating recorded | 1,849 | 6,534 |
| Rating count recorded | 0 | 6,534 |
| Brand unrecorded | 5,864 | 0 |
| Category unrecorded | 2 | 7,393 |
| Attributes unrecorded | 67 | 0 |
