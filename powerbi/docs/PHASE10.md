# Phase 10 Desktop corrections

The saved project retains the Desktop lineage tags, page and visual IDs, report metadata, local settings and configured DataFolder. Close any older copy of the same project before reopening IntelliMarket.pbip from disk. Select Home > Refresh.

## Runtime repairs

Microsoft Tabular Object Model reproduced the issue. The comparison_category expression contained dataType and summarizeBy metadata as DAX. Shared Category had the same defect with formatString. Both expressions now use explicit TMDL fences, including in the generator. The parser checks all 37 measure expressions and nine calculated column expressions.

The comparison slicer and matrix retain a nonblank mapped-category filter. The matrix measures return values only when both marketplaces have recorded prices for the category under the remaining filters. Nine groups qualify. The original mapping includes Kurta Sets, which has only Myntra listings and yields an empty comparison matrix.

## Presentation

All four pages use a 1600 × 900 canvas. Taller cards and slicers, full count values, two-decimal prices, readable labels, compact listing labels and fixed table widths improve readability. Unknown category is a presentation label for missing top categories. Full source names, categories and identifiers remain in the model. The price-band matrix is now a four-column table with listing counts and separate marketplace medians. All 56 visual IDs are retained. Long detail tables still scroll vertically.

The rating-price scatter uses a bubble per marketplace and per 0.2-wide log10(1 + price) and rating bin. Bubble size counts the underlying listings. Coordinates are within-bin means, and tooltips show minimum and maximum original recorded prices. All listings with recorded prices and ratings contribute, including zero prices and outliers. Historical notices and the marketplace palette remain in place.

## Verification

An isolated copy opened and refreshed in Power BI Desktop 2.160.1151.0. All four pages rendered after refresh. The comparison matrix displayed nine groups and filtered to one row when Kurtas was selected. Exact counts and formatted price and rating KPIs were visible. The subsequent price-band and density refinements passed static validation. The Windows automation helper could not reconnect for a final visual pass. Verify those two visuals and the in-canvas navigation at the target embed size after reopening.

The declared Desktop visualContainer 2.15.0 and report 3.4.0 schema URLs returned HTTP 404. The validator used the closest published schemas for those documents. Saved schema versions and the Desktop-only linguisticSchemaSyncVersion were preserved. The compatibility check excludes that Desktop-only property.

## CSV permissions

The previous staging directory reproduced the Windows issue, with a protected ACL and zero inherited rules. The exporter now stages sibling files directly in the destination directory before replacing each CSV. A probe created this way inherited seven rules with an unprotected ACL. The six existing export checksums matched. No access was broadened. If an older copy still fails, verify inherited access for the account running Desktop and select the correct DataFolder.
