"""Cross-check project bindings and measure semantics independently of Desktop."""
from collections import Counter, defaultdict
from decimal import Decimal
from itertools import combinations
import json
from math import log10
from pathlib import Path
import re
from statistics import mean, median
import unittest

from test_exports import ROOT, load

REPORT = ROOT / "IntelliMarket.Report"
MODEL = ROOT / "IntelliMarket.SemanticModel"
PAGES = REPORT / "definition/pages"
ROLES = {
    "cardVisual": {"Data"}, "tableEx": {"Values"}, "pivotTable": {"Rows", "Columns", "Values"},
    "slicer": {"Values"}, "scatterChart": {"Category", "X", "Y", "Series", "Size", "Tooltips"},
    "donutChart": {"Category", "Y", "Tooltips"},
    "clusteredBarChart": {"Category", "Y", "Series", "Tooltips"},
    "clusteredColumnChart": {"Category", "Y", "Series"},
}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def objects(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from objects(value)
    elif isinstance(node, list):
        for value in node:
            yield from objects(value)


def listing_rows():
    return load("fact_product")


class ProjectTests(unittest.TestCase):
    def test_project_links_tables_types_and_relationships(self):
        project = read_json(ROOT / "IntelliMarket.pbip")
        self.assertEqual(ROOT / project["artifacts"][0]["report"]["path"], REPORT)
        reference = read_json(REPORT / "definition.pbir")["datasetReference"]["byPath"]["path"]
        self.assertEqual((REPORT / reference).resolve(), MODEL.resolve())
        relationships = (MODEL / "definition/relationships.tmdl").read_text(encoding="utf-8")
        self.assertEqual(set(re.findall(r"fromColumn: fact_product\.(\w+)\s+toColumn: (\w+)\.(\w+)", relationships)), {
            ("marketplace", "dim_marketplace", "marketplace"), ("brand_id", "dim_brand", "brand_id"),
            ("category_id", "dim_category", "category_id"), ("price_band_id", "dim_price_band", "price_band_id"),
        })
        self.assertNotIn("bothDirections", relationships)
        for path in (MODEL / "definition/tables").glob("*.tmdl"):
            source = path.read_text(encoding="utf-8")
            self.assertIn(f'Folder & "/{path.stem}.csv"', source)
            self.assertIn("Encoding=65001", source)
            self.assertEqual(set(re.findall(r"sourceColumn: (\w+)", source)), load(path.stem)[0].keys())
            self.assertNotIn("source_lineage", source)

    def test_report_pages_layout_roles_interactions_and_references(self):
        columns = {}
        measures = {}
        for path in (MODEL / "definition/tables").glob("*.tmdl"):
            source = path.read_text(encoding="utf-8")
            columns[path.stem] = set(re.findall(r"^\tcolumn (\w+)", source, re.M))
            measures[path.stem] = set(re.findall(r"^\tmeasure '([^']+)'", source, re.M))
        metadata = read_json(PAGES / "pages.json")
        self.assertEqual(len(metadata["pageOrder"]), 4)
        self.assertIn(metadata["activePageName"], metadata["pageOrder"])
        for name in metadata["pageOrder"]:
            page = read_json(PAGES / name / "page.json")
            self.assertEqual(page["name"], name)
            self.assertEqual(page["width"] * 9, page["height"] * 16)
            visuals = {}
            for path in (PAGES / name / "visuals").glob("*/visual.json"):
                container = read_json(path)
                self.assertEqual(path.parent.name, container["name"])
                visual = container["visual"]
                chart = visual["visualType"]
                visuals[container["name"]] = (chart, container["position"])
                if chart in ROLES:
                    query = visual["query"]["queryState"]
                    self.assertTrue(query.keys() <= ROLES[chart])
                    refs = [p["queryRef"] for role in query.values() for p in role["projections"]]
                    self.assertEqual(len(refs), len(set(refs)))
                for node in objects(container):
                    for kind, schema in (("Column", columns), ("Measure", measures)):
                        if kind in node:
                            expression = node[kind]
                            ref = expression["Expression"]["SourceRef"]
                            entity = ref.get("Entity", ref.get("Source"))
                            self.assertIn(expression["Property"], schema[entity], (name, path.name))
            self.assertEqual(Counter(chart for chart, _ in visuals.values())["slicer"], 3)
            self.assertEqual(visuals["navigation"][0], "pageNavigator")
            self.assertEqual(visuals["historical"][0], "textbox")
            for _, bounds in visuals.values():
                self.assertLessEqual(bounds["x"] + bounds["width"], page["width"])
                self.assertLessEqual(bounds["y"] + bounds["height"], page["height"])
                self.assertGreaterEqual(min(bounds["x"], bounds["y"]), 0)
            for (_, a), (_, b) in combinations(visuals.values(), 2):
                self.assertTrue(a["x"] + a["width"] <= b["x"] or b["x"] + b["width"] <= a["x"]
                                or a["y"] + a["height"] <= b["y"] or b["y"] + b["height"] <= a["y"])
            expected = {(source, target, "DataFilter")
                        for source, (kind, _) in visuals.items() if kind == "slicer"
                        for target, (target_kind, _) in visuals.items() if target_kind in ROLES and target_kind != "slicer"}
            self.assertEqual({(i["source"], i["target"], i["type"]) for i in page["visualInteractions"]}, expected)

    def test_dashboard_measure_values_against_sqlite(self):
        from sqlite3 import connect
        catalog = ROOT.parent / "rag_chatbot/artifacts/catalog.sqlite3"
        db = connect(catalog.resolve().as_uri() + "?mode=ro", uri=True)
        self.addCleanup(db.close)
        listings = listing_rows()
        for market in (None, "flipkart", "myntra"):
            clause = "WHERE (? IS NULL OR platform=?)"
            params = market, market
            rows = [r for r in listings if market is None or r["marketplace"] == market]
            prices = [Decimal(r["recorded_price"]) for r in rows if r["recorded_price"]]
            ratings = [float(r["rating"]) for r in rows if r["rating"]]
            counts = [int(r["rating_count"]) for r in rows if r["rating_count"]]
            eligible = [float(r["discount_fraction"]) for r in rows if r["discount_fraction"]]
            count, brands, priced, avg_price, rated, avg_rating, sum_counts, rank_count = db.execute(f"""
                SELECT count(*),count(DISTINCT CASE WHEN brand IS NOT NULL THEN nullif(brand_key,'') END),
                       count(price_minor),avg(price_minor)/100.,count(rating),avg(rating),sum(rating_count),
                       count(CASE WHEN rating IS NOT NULL AND rating_count>=10 THEN 1 END)
                FROM products {clause}
            """, params).fetchone()
            self.assertEqual((len(rows), len({r["brand_id"] for r in rows} - {"0"}), len(prices), len(ratings)),
                             (count, brands, priced, rated))
            self.assertAlmostEqual(float(mean(prices)), avg_price)
            ordered = [r[0] for r in db.execute(f"""
                SELECT price_minor FROM products {clause} AND price_minor IS NOT NULL
                ORDER BY price_minor LIMIT ? OFFSET ?
            """, (*params, 2 - priced % 2, (priced - 1) // 2))]
            self.assertEqual(median(prices), Decimal(sum(ordered)) / (len(ordered) * 100))
            self.assertAlmostEqual(mean(ratings), avg_rating)
            self.assertEqual(sum(counts) if counts else None, sum_counts)
            self.assertEqual(sum(bool(r["rating"]) and int(r["rating_count"] or 0) >= 10 for r in rows), rank_count)
            valid, positive, avg_discount = db.execute(f"""
                SELECT count(*),count(CASE WHEN price_minor<retail_price_minor THEN 1 END),
                       avg(1.0*(retail_price_minor-price_minor)/retail_price_minor)
                FROM products {clause} AND platform='flipkart' AND retail_price_minor>0
                     AND price_minor BETWEEN 0 AND retail_price_minor
            """, params).fetchone()
            self.assertEqual((len(eligible), sum(r > 0 for r in eligible)), (valid, positive))
            if eligible:
                self.assertAlmostEqual(mean(eligible), avg_discount)
            else:
                self.assertIsNone(avg_discount)

    def test_comparison_taxonomy_preserves_grain_and_populates_shared_categories(self):
        from sqlite3 import connect
        catalog = ROOT.parent / "rag_chatbot/artifacts/catalog.sqlite3"
        db = connect(catalog.resolve().as_uri() + "?mode=ro", uri=True)
        self.addCleanup(db.close)
        tmdl = (MODEL / "definition/tables/dim_category.tmdl").read_text(encoding="utf-8")
        label_rules = [(label, set(re.findall(r'PATHCONTAINS\(Segments, "([^"]+)"\)', line)))
                       for line, label in re.findall(r'((?:PATHCONTAINS.*)), "([^"]+)",', tmdl)]
        self.assertEqual(len(label_rules), 10)
        lookup = {}
        for category in load("dim_category"):
            parts = set(category["category_path"].split(" > "))
            lookup[category["category_id"]] = next((label for label, aliases in label_rules if parts & aliases), None)
        exported = defaultdict(Counter)
        for row in listing_rows():
            label = lookup[row["category_id"]]
            if label and row["recorded_price"]:
                exported[label][row["marketplace"]] += 1
        sqlite_totals = db.execute("""
            WITH matched AS (
                SELECT products.id, platform,
                       CASE j.value WHEN 'Kurtas & Kurtis' THEN 'Kurtas' ELSE j.value END AS label
                FROM products, json_each(category_path) j
                WHERE price_minor IS NOT NULL AND j.value IN ('Kurta Sets','Kurtas','Kurtas & Kurtis','T-Shirts',
                      'Shirts','Jeans','Sarees','Jackets','Trousers','Dresses','Tops')
            )
            SELECT label,platform,count(DISTINCT id) FROM matched GROUP BY label,platform
        """)
        self.assertEqual({(k, m): n for k, totals in exported.items() for m, n in totals.items()},
                         {(k, m): n for k, m, n in sqlite_totals})
        self.assertEqual(sum(len(group) == 2 for group in exported.values()), 9)

    def test_runtime_fixes_are_present(self):
        dimensions = MODEL / "definition/tables"
        dim = (dimensions / "dim_category.tmdl").read_text(encoding="utf-8")
        fact = (dimensions / "fact_product.tmdl").read_text(encoding="utf-8")
        expected = (
            (dim, "column comparison_category", ("dataType: string", "summarizeBy: none")),
            (fact, "measure 'Shared Category'", ("formatString: #,0",)),
        )
        fence = chr(96) * 3
        for definition, declaration, properties in expected:
            with self.subTest(declaration=declaration):
                pattern = (
                    rf"^\t{re.escape(declaration)} =[ ]*(?P<fence>{fence})?\n"
                    rf"(?P<dax>(?:\t{{3}}(?!{fence}$)[^\n]+\n)+)"
                    rf"(?(fence)\t{{3}}{fence}\n)"
                    r"(?P<metadata>(?:\t{2}(?!\t)[^\n]+\n)+)"
                )
                match = re.search(pattern, definition, re.MULTILINE)
                self.assertIsNotNone(match, "Expected a bounded DAX expression followed by TMDL metadata")
                self.assertRegex(match["dax"], r"(?m)^\s*RETURN\b")
                self.assertNotRegex(
                    match["dax"], r"(?im)^\s*(dataType|summarizeBy|formatString|lineageTag|sortByColumn)\s*:"
                )
                for prop in properties:
                    self.assertIn("\t\t" + prop, match["metadata"].splitlines())
        self.assertIn("Unknown category", dim)
        self.assertIn("LOG10(1 + Price)", fact)
        scatter = read_json(PAGES / "ProductRatingAnalytics/visuals/scatter/visual.json")
        state = scatter["visual"]["query"]["queryState"]
        self.assertEqual(state["Category"]["projections"][0]["queryRef"], "fact_product.scatter_bin")
        self.assertEqual(state["Size"]["projections"][0]["queryRef"], "fact_product.Priced Products")
        comparison = PAGES / "MarketplaceComparison/visuals"
        for name in ("slicer0", "sharedCategories"):
            visual = read_json(comparison / name / "visual.json")
            filters = visual["filterConfig"]["filters"]
            self.assertEqual(filters[0]["field"]["Column"]["Property"], "comparison_category")
            self.assertEqual(filters[0]["type"], "Categorical")
        matrix = read_json(comparison / "sharedCategories/visual.json")
        values = matrix["visual"]["query"]["queryState"]["Values"]["projections"]
        self.assertTrue(all(item["field"]["Measure"]["Property"].startswith("Comparable ") for item in values))
        self.assertEqual(len(list(PAGES.glob("*/visuals/*/visual.json"))), 56)

    def test_coverage_and_scatter_preserve_catalog_values(self):
        from sqlite3 import connect
        catalog = ROOT.parent / "rag_chatbot/artifacts/catalog.sqlite3"
        db = connect(catalog.resolve().as_uri() + "?mode=ro", uri=True)
        self.addCleanup(db.close)
        listings = listing_rows()
        observed = db.execute("""
            SELECT platform, count(*), count(rating), count(rating_count),
                   count(CASE WHEN json_array_length(category_path)>0 THEN 1 END),
                   count(CASE WHEN brand IS NOT NULL THEN 1 END),
                   count(CASE WHEN EXISTS (SELECT 1 FROM json_each(attributes)) THEN 1 END),
                   count(CASE WHEN rating IS NOT NULL AND price_minor IS NOT NULL THEN 1 END),
                   min(CASE WHEN rating IS NOT NULL THEN price_minor END),
                   max(CASE WHEN rating IS NOT NULL THEN price_minor END)
            FROM products GROUP BY platform
        """)
        for market, n, rated, counts, category, brand, attributes, points, low, high in observed:
            rows = [row for row in listings if row["marketplace"] == market]
            self.assertEqual(len(rows), n)
            self.assertEqual(sum(int(row["has_rating"]) for row in rows), rated)
            self.assertEqual(sum(int(row["has_rating_count"]) for row in rows), counts)
            for field, available in (("category", category), ("brand", brand), ("attributes", attributes)):
                self.assertEqual(n - sum(int(row["missing_" + field]) for row in rows), available)
            bins = defaultdict(list)
            for row in rows:
                if row["recorded_price"] and row["rating"]:
                    price = Decimal(row["recorded_price"])
                    key = (int(log10(1 + price) * 5), int(Decimal(row["rating"]) * 5))
                    bins[key].append(price)
            self.assertEqual(sum(len(prices) for prices in bins.values()), points)
            self.assertEqual(min(min(prices) for prices in bins.values()) * 100, low)
            self.assertEqual(max(max(prices) for prices in bins.values()) * 100, high)
