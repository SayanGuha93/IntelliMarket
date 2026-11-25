"""Build the editable Phase 9 project from the Phase 8 CSV contract."""
import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "IntelliMarket.Report"
MODEL = ROOT / "IntelliMarket.SemanticModel"
DEFINITION = REPORT / "definition"
TMDL = MODEL / "definition"
FABRIC = "https://developer.microsoft.com/json-schemas/fabric"
REPORT_SCHEMA = f"{FABRIC}/item/report/definition"
NAVY, WHITE, BLUE, PINK = "#101E37", "#FFFFFF", "#2563EB", "#DB2777"
FACT = "fact_product"

COLUMNS = {
    "dim_marketplace": "marketplace:s marketplace_name:s",
    "dim_brand": "brand_id:i brand_key:s brand_name:s",
    "dim_category": "category_id:i category_path:s top_category:s leaf_category:s category_basis:s category_depth:i",
    "dim_price_band": "price_band_id:i price_band:s",
    FACT: """product_id:i marketplace:s source_product_id:s product_name:s brand_id:i category_id:i
        price_band_id:i colour:s recorded_price_field:s recorded_price:f retail_price:f discounted_price:f
        discount_amount:f discount_fraction:d rating:d overall_rating:d rating_count:i has_rating:i
        has_overall_rating:i has_rating_count:i missing_recorded_price:i missing_retail_price:i missing_brand:i
        missing_category:i missing_attributes:i missing_colour:i missing_observation_date:i has_conflicts:i
        observed_at:s product_url:s attributes_json:s""",
}
RELATIONSHIPS = {
    "dim_marketplace": "marketplace", "dim_brand": "brand_id",
    "dim_category": "category_id", "dim_price_band": "price_band_id",
}
TYPES = {
    "s": ("string", "type text"), "i": ("int64", "Int64.Type"),
    "f": ("decimal", "Currency.Type"), "d": ("double", "type number"),
}
COMPARISON_RULES = {
    "Kurta Sets": ("Kurta Sets",), "Kurtas": ("Kurtas", "Kurtas & Kurtis"),
    "T-Shirts": ("T-Shirts",), "Shirts": ("Shirts",), "Jeans": ("Jeans",),
    "Sarees": ("Sarees",), "Jackets": ("Jackets",), "Trousers": ("Trousers",),
    "Dresses": ("Dresses",), "Tops": ("Tops",),
}
CATEGORY_COMPARISON = (
    'VAR Segments = SUBSTITUTE(dim_category[category_path], " > ", "|")\n'
    "RETURN SWITCH(TRUE(),\n"
    + "".join(
        "    " + " || ".join(f'PATHCONTAINS(Segments, "{alias}")' for alias in aliases)
        + f', "{label}",\n'
        for label, aliases in COMPARISON_RULES.items()
    )
    + "    BLANK())"
)
CALCULATED = {
    FACT: {
        "listing": ("string", 'fact_product[product_name] & " (" & fact_product[marketplace] & ":" & fact_product[source_product_id] & ")"', None),
        "listing_compact": ("string", 'LEFT(fact_product[product_name], 38) & IF(LEN(fact_product[product_name]) > 38, "…", "") & " · " & IF(fact_product[marketplace] = "flipkart", "FK ", "MY ") & fact_product[source_product_id]', None),
        "scatter_bin": ("string", 'VAR Price = fact_product[recorded_price] VAR Stars = fact_product[rating] RETURN IF(NOT ISBLANK(Price) && NOT ISBLANK(Stars), INT(LOG10(1 + Price) * 5) & "|" & INT(Stars * 5))', None),
        "discount_band_order": ("int64", "IF(ISBLANK(fact_product[discount_fraction]), BLANK(), IF(fact_product[discount_fraction] = 0, 0, MIN(4, 1 + INT(fact_product[discount_fraction] * 4))))", None),
        "discount_band": ("string", 'IF(ISBLANK(fact_product[discount_band_order]), BLANK(), SWITCH(fact_product[discount_band_order], 0, "0%", 1, ">0% to <25%", 2, "25% to <50%", 3, "50% to <75%", 4, "75% to 100%"))', "discount_band_order"),
        "rating_band_order": ("int64", "IF(ISBLANK(fact_product[rating]), BLANK(), INT(fact_product[rating]))", None),
        "rating_band": ("string", 'IF(ISBLANK(fact_product[rating_band_order]), BLANK(), SWITCH(fact_product[rating_band_order], 0, "0 to <1", 1, "1 to <2", 2, "2 to <3", 3, "3 to <4", 4, "4 to <5", 5, "5"))', "rating_band_order"),
    },
    "dim_category": {
        "comparison_category": ("string", CATEGORY_COMPARISON, None),
        "category_display": ("string", 'IF(LEN(TRIM(dim_category[top_category])) = 0, "Unknown category", dim_category[top_category])', None),
    },
}

COUNT, NUMBER, PERCENT = "#,0", "#,0.00", "0.0%"
MEASURES = {
    "Product Count": ("COUNTROWS(fact_product)", COUNT),
    "Flipkart Products": ('CALCULATE([Product Count], KEEPFILTERS(dim_marketplace[marketplace] = "flipkart"))', COUNT),
    "Myntra Products": ('CALCULATE([Product Count], KEEPFILTERS(dim_marketplace[marketplace] = "myntra"))', COUNT),
    "Known Brands": ("CALCULATE(DISTINCTCOUNT(fact_product[brand_id]), KEEPFILTERS(fact_product[brand_id] <> 0))", COUNT),
    "Categories Recorded": ("CALCULATE(DISTINCTCOUNT(fact_product[category_id]), KEEPFILTERS(fact_product[category_id] <> 0))", COUNT),
    "Marketplace Share": ("DIVIDE([Product Count], CALCULATE([Product Count], REMOVEFILTERS(dim_marketplace)))", PERCENT),
    "Priced Products": ("COUNT(fact_product[recorded_price])", COUNT),
    "Price Coverage": ("DIVIDE([Priced Products], [Product Count])", PERCENT),
    "Average Recorded Price": ("AVERAGE(fact_product[recorded_price])", NUMBER),
    "Median Recorded Price": ("MEDIAN(fact_product[recorded_price])", NUMBER),
    "Discount Eligible Products": ("COUNT(fact_product[discount_fraction])", COUNT),
    "Discounted Products": ("CALCULATE([Product Count], KEEPFILTERS(fact_product[discount_fraction] > 0))", COUNT),
    "Average Valid Discount": ("AVERAGE(fact_product[discount_fraction])", PERCENT),
    "Recorded Retail Price": ("SELECTEDVALUE(fact_product[retail_price])", NUMBER),
    "Recorded Listing Price": ("SELECTEDVALUE(fact_product[recorded_price])", NUMBER),
    "Listing Discount Amount": ("SELECTEDVALUE(fact_product[discount_amount])", NUMBER),
    "Rated Products": ("SUM(fact_product[has_rating])", COUNT),
    "Rating Coverage": ("DIVIDE([Rated Products], [Product Count])", PERCENT),
    "Average Recorded Rating": ("AVERAGE(fact_product[rating])", NUMBER),
    "Products With Rating Count": ("SUM(fact_product[has_rating_count])", COUNT),
    "Reported Rating Count": ("SUM(fact_product[rating_count])", COUNT),
    "Missing Rating": ("[Product Count] - [Rated Products]", COUNT),
    "Missing Attributes": ("SUM(fact_product[missing_attributes])", COUNT),
    "Category Coverage": ("DIVIDE([Product Count] - SUM(fact_product[missing_category]), [Product Count])", PERCENT),
    "Brand Coverage": ("DIVIDE([Product Count] - SUM(fact_product[missing_brand]), [Product Count])", PERCENT),
    "Attribute Coverage": ("DIVIDE([Product Count] - [Missing Attributes], [Product Count])", PERCENT),
    "Shared Category": ("""VAR Label = SELECTEDVALUE(dim_category[comparison_category])
VAR Flipkart = CALCULATE([Priced Products], REMOVEFILTERS(dim_marketplace), dim_marketplace[marketplace] = "flipkart")
VAR Myntra = CALCULATE([Priced Products], REMOVEFILTERS(dim_marketplace), dim_marketplace[marketplace] = "myntra")
RETURN IF(NOT ISBLANK(Label) && Flipkart > 0 && Myntra > 0, 1, 0)""", COUNT),
    "Ranking Rating": ("IF(HASONEVALUE(fact_product[product_id]) && SELECTEDVALUE(fact_product[rating_count]) >= 10, SELECTEDVALUE(fact_product[rating]))", NUMBER),
    "Ranking Rating Count": ("IF(NOT ISBLANK([Ranking Rating]), SELECTEDVALUE(fact_product[rating_count]))", COUNT),
    "Comparable Priced Listings": ("IF([Shared Category] = 1, [Priced Products])", COUNT),
    "Comparable Median Price": ("IF([Shared Category] = 1, [Median Recorded Price])", NUMBER),
    "Comparable Average Price": ("IF([Shared Category] = 1, [Average Recorded Price])", NUMBER),
    "Log Recorded Price": ("AVERAGEX(FILTER(fact_product, NOT ISBLANK(fact_product[recorded_price])), LOG10(1 + fact_product[recorded_price]))", NUMBER),
    "Minimum Recorded Price": ("MIN(fact_product[recorded_price])", NUMBER),
    "Maximum Recorded Price": ("MAX(fact_product[recorded_price])", NUMBER),
    "Flipkart Median Recorded Price": ('CALCULATE([Median Recorded Price], KEEPFILTERS(dim_marketplace[marketplace] = "flipkart"))', NUMBER),
    "Myntra Median Recorded Price": ('CALCULATE([Median Recorded Price], KEEPFILTERS(dim_marketplace[marketplace] = "myntra"))', NUMBER),
}


def declaration(kind, name, dax):
    prefix = f"\t{kind} {name} ="
    if "\n" not in dax:
        return [f"{prefix} {dax}"]
    return [prefix + " ```", *("\t\t\t" + part for part in dax.splitlines()), "\t\t\t```"]


def write(path, contents):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents.rstrip() + "\n", encoding="utf-8", newline="\n")


def jsonify(path, obj):
    write(path, json.dumps(obj, ensure_ascii=False, indent=2))


def m_text(text):
    return '"' + text.replace('"', '""') + '"'


def model_path(folder):
    prefix = 'expression DataFolder = '
    value = folder.resolve().as_posix() if folder else "SET_DATA_FOLDER"
    return prefix + m_text(value) + ' meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]'


def build_model(folder):
    jsonify(MODEL / "definition.pbism", {
        "$schema": f"{FABRIC}/item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.0", "settings": {"qnaEnabled": False},
    })
    write(TMDL / "database.tmdl", "database\n\tcompatibilityLevel: 1601")
    write(TMDL / "model.tmdl", """model Model
\tculture: en-US
\tdefaultPowerBIDataSourceVersion: powerBI_V3
\tdiscourageImplicitMeasures
\tsourceQueryCulture: en-US

annotation __PBI_TimeIntelligenceEnabled = 0

""" + "\n".join(f"ref table {table}" for table in COLUMNS))
    write(TMDL / "expressions.tmdl", model_path(folder) + "\n\tannotation PBI_ResultType = Text")
    write(TMDL / "relationships.tmdl", "\n\n".join(
        f"relationship ProductTo{dim.removeprefix('dim_').title().replace('_', '')}\n"
        f"\tfromColumn: {FACT}.{key}\n\ttoColumn: {dim}.{key}"
        for dim, key in RELATIONSHIPS.items()
    ))
    for table, specification in COLUMNS.items():
        mappings = [pair.split(":") for pair in specification.split()]
        with (ROOT / "data" / f"{table}.csv").open(encoding="utf-8-sig", newline="") as stream:
            if next(csv.reader(stream)) != [column for column, _ in mappings]:
                raise ValueError(f"Unexpected CSV header for {table}")
        lines = [f"table {table}"]
        if table == FACT:
            for title, (dax, formatting) in MEASURES.items():
                lines += ["", *declaration("measure", f"'{title}'", dax)]
                lines += [f"\t\tformatString: {formatting}"]
        for column, kind in mappings:
            lines += ["", f"\tcolumn {column}", f"\t\tdataType: {TYPES[kind][0]}",
                      "\t\tsummarizeBy: none", f"\t\tsourceColumn: {column}"]
            if column == RELATIONSHIPS.get(table) or (table == FACT and column == "product_id"):
                lines += ["\t\tisKey"]
            if table == "dim_price_band" and column == "price_band":
                lines += ["\t\tsortByColumn: price_band_id"]
        for column, (kind, dax, sort_by) in CALCULATED.get(table, {}).items():
            lines += ["", *declaration("column", column, dax)]
            lines += [f"\t\tdataType: {kind}", "\t\tsummarizeBy: none"]
            if sort_by:
                lines += [f"\t\tsortByColumn: {sort_by}"]
        conversions = ", ".join(f'{{"{column}", {TYPES[kind][1]}}}' for column, kind in mappings)
        lines += ["", f"\tpartition {table} = m", "\t\tmode: import", "\t\tsource =",
                  "\t\t\tlet",
                  ' \t\t\t\tFolder = if DataFolder = "SET_DATA_FOLDER" then error "Set DataFolder to the full powerbi/data path before refresh." else DataFolder,',
                  f'\t\t\t\tRaw = Csv.Document(File.Contents(Folder & "/{table}.csv"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),',
                  "\t\t\t\tHeaders = Table.PromoteHeaders(Raw, [PromoteAllScalars=true]),",
                  f'\t\t\t\tTyped = Table.TransformColumnTypes(Headers, {{{conversions}}}, "en-US")',
                  "\t\t\tin", "\t\t\t\tTyped"]
        write(TMDL / "tables" / f"{table}.tmdl", "\n".join(lines).replace("\n \t", "\n\t"))


def field(binding, alias=False):
    entity, prop = binding.split(".", 1) if "." in binding else (FACT, binding)
    kind = "Measure" if prop in MEASURES else "Column"
    source = {"Source": entity} if alias else {"Entity": entity}
    return {kind: {"Expression": {"SourceRef": source}, "Property": prop}}


def projection(binding, active):
    definition = field(binding)
    inner = next(iter(definition.values()))
    entity = inner["Expression"]["SourceRef"]["Entity"]
    prop = inner["Property"]
    result = {"field": definition, "queryRef": f"{entity}.{prop}", "nativeQueryRef": prop}
    if active:
        result["active"] = True
    return result


def literal(value):
    return {"expr": {"Literal": {"Value": value}}}


def color(value):
    return {"solid": {"color": literal(f"'{value}'")}}


def properties(**values):
    return [{"properties": values}]


def src(entity):
    return {"Name": entity, "Entity": entity, "Type": 0}


def filter_expr(binding, condition, kind="Advanced"):
    table = next(iter(field(binding).values()))["Expression"]["SourceRef"]["Entity"]
    return {"name": "Filter" + binding.replace(".", "").replace(" ", ""),
            "field": field(binding), "type": kind,
            "filter": {"Version": 2, "From": [src(table)], "Where": [{"Condition": condition}]}}


def comparison(binding, kind, value):
    return filter_expr(binding, {"Comparison": {
        "ComparisonKind": kind, "Left": field(binding, alias=True),
        "Right": {"Literal": {"Value": value}},
    }})


def nonblank(binding):
    condition = {"In": {"Expressions": [field(binding, alias=True)], "Values": [[{"Literal": {"Value": "null"}}]]}}
    return filter_expr(binding, {"Not": {"Expression": condition}}, "Categorical")


def top(binding, measure, count, *, condition=None, tie_break=None):
    entity = binding.split(".", 1)[0] if "." in binding else FACT
    column = field(binding, alias=True)
    sources = [src(entity)] if entity == FACT else [src(entity), src(FACT)]
    query = {"Version": 2, "From": sources, "Select": [{**column, "Name": "field"}],
             "OrderBy": [{"Direction": 2, "Expression": field(measure, alias=True)}], "Top": count}
    if condition:
        query["Where"] = condition["filter"]["Where"]
    if tie_break:
        query["OrderBy"].append({"Direction": 2, "Expression": field(tie_break, alias=True)})
    return {
        "name": "FilterTop" + str(count), "field": field(binding), "type": "TopN",
        "filter": {"Version": 2, "From": [
            {"Name": "subquery", "Expression": {"Subquery": {"Query": query}}, "Type": 2}, src(entity)
        ], "Where": [{"Condition": {"In": {"Expressions": [column],
                                          "Table": {"SourceRef": {"Source": "subquery"}}}}}]},
    }


def text_config(text, font_size, foreground=WHITE, bold=False):
    style = {"fontFamily": "Segoe UI", "fontSize": f"{font_size}pt", "color": foreground}
    if bold:
        style["fontWeight"] = "bold"
    return {"general": properties(paragraphs=[{"textRuns": [{"value": text, "textStyle": style}]}])}


def create_visual(path, name, chart, title, position, roles=None, sorts=(), filters=(), objects=None):
    x, y, width, height = position
    v = {"visualType": chart}
    if roles:
        v["query"] = {"queryState": {
            role: {"projections": [projection(binding, role == "Values" and chart == "slicer") for binding in bindings]}
            for role, bindings in roles.items()
        }}
        if sorts:
            v["query"]["sortDefinition"] = {"sort": [
                {"field": field(binding), "direction": direction} for binding, direction in sorts
            ]}
        v["drillFilterOtherVisuals"] = True
    if chart == "slicer":
        v["objects"] = {"data": properties(mode=literal("'Dropdown'"))}
    if objects:
        v["objects"] = objects
    if roles and chart in {"donutChart", "clusteredBarChart", "clusteredColumnChart", "scatterChart"}:
        market_roles = [role for role in ("Category", "Series") if MARKET in roles.get(role, ())]
        if market_roles and len(roles.get("Y", ())) == 1:
            v.setdefault("objects", {})["dataPoint"] = [
                {"properties": {"fill": color(shade)}, "selector": {"data": [{"scopeId": {
                    "Comparison": {"ComparisonKind": 0, "Left": field(MARKET),
                                   "Right": {"Literal": {"Value": f"'{market}'"}}}
                }}]}}
                for market, shade in (("Flipkart", BLUE), ("Myntra", PINK))
            ]
    formatting = {"background": properties(
        show=literal("true"), color=color(NAVY if chart == "textbox" else WHITE),
        transparency=literal("0D"))}
    if title:
        formatting["title"] = properties(show=literal("true"), text=literal("'" + title.replace("'", "''") + "'"),
                                        fontColor=color(NAVY), fontFamily=literal("'Segoe UI Semibold'"))
    v["visualContainerObjects"] = formatting
    container = {
        "$schema": f"{REPORT_SCHEMA}/visualContainer/2.9.0/schema.json", "name": name,
        "position": {"x": x, "y": y, "width": width, "height": height, "z": y * 10 + x, "tabOrder": y * 10 + x},
        "visual": v,
    }
    if filters:
        container["filterConfig"] = {"filters": list(filters)}
    refine_visual(container)
    jsonify(path / "visuals" / name / "visual.json", container)


MARKET = "dim_marketplace.marketplace_name"
CATEGORY = "dim_category.category_display"
LEAF = "dim_category.comparison_category"
BRAND = "dim_brand.brand_name"
BAND = "dim_price_band.price_band"
LISTING = f"{FACT}.listing"
COMPACT = f"{FACT}.listing_compact"
HISTORY = "Historical dataset values • Flipkart crawl 2015–2016 • Myntra date unverified • Currency unspecified • Current prices and availability unverified"


DISPLAY_NAMES = {
    "marketplace_name": "Marketplace", "category_display": "Category",
    "comparison_category": "Comparison category", "brand_name": "Brand",
    "price_band": "Recorded price band", "discount_band": "Discount band",
    "rating_band": "Rating band", "listing": "Listing", "listing_compact": "Product / source ID",
    "Comparable Priced Listings": "Priced listings", "Comparable Median Price": "Median price",
    "Comparable Average Price": "Avg. price", "Ranking Rating": "Rating",
    "Ranking Rating Count": "Rating count", "Recorded Retail Price": "Retail price",
    "Recorded Listing Price": "Recorded price", "Listing Discount Amount": "Discount amount",
    "Average Valid Discount": "Discount %", "Log Recorded Price": "Log10(1 + recorded price)",
    "scatter_bin": "Price and rating bin", "Minimum Recorded Price": "Lowest recorded price",
    "Maximum Recorded Price": "Highest recorded price", "Flipkart Median Recorded Price": "Flipkart median",
    "Myntra Median Recorded Price": "Myntra median",
}


def set_object(objects, name, values, selector=None):
    entries = objects.setdefault(name, [])
    for entry in entries:
        if entry.get("selector") == selector:
            entry["properties"].update(values)
            return
    entry = {"properties": values}
    if selector is not None:
        entry["selector"] = selector
    entries.append(entry)


def refine_visual(container):
    """Apply shared embed layout and presentation to Phase 9 visual definitions."""
    name, position = container["name"], container["position"]
    y, height = {
        16: (16, 54), 74: (80, 98), 160: (188, 112),
        207: (244, 252), 451: (508, 320), 516: (588, 240),
        500: (566, 262), 768: (840, 44),
    }.get(position["y"], (310, 266 if position["height"] == 246 else 244))
    if name == "comparisonScope":
        height = 44
    position.update(x=round(position["x"] * 10 / 9), width=round(position["width"] * 10 / 9), y=y, height=height)
    visual = container["visual"]
    chart = visual["visualType"]
    state = visual.get("query", {}).get("queryState", {})
    for grouping in state.values():
        for item in grouping["projections"]:
            prop = next(iter(item["field"].values()))["Property"]
            if prop in DISPLAY_NAMES:
                item["displayName"] = DISPLAY_NAMES[prop]
    objects = visual.setdefault("objects", {})
    formatting = visual["visualContainerObjects"]
    if chart == "cardVisual":
        default = {"id": "default"}
        prop = state["Data"]["projections"][0]["field"]["Measure"]["Property"]
        precision = {COUNT: 0, NUMBER: 2, PERCENT: 1}[MEASURES[prop][1]]
        set_object(objects, "value", dict(fontSize=literal("32D"), labelDisplayUnits=literal("1D"),
                                         labelPrecision=literal(f"{precision}L")), default)
        set_object(objects, "label", dict(show=literal("false")), default)
        set_object(objects, "padding", dict(paddingUniform=literal("6D")), default)
        set_object(objects, "layout", dict(paddingUniform=literal("0D")), default)
    elif chart == "slicer":
        set_object(objects, "header", dict(show=literal("false")))
    elif chart == "tableEx":
        entries = state["Values"]["projections"]
        widths = {
            "topDiscounts": (313, 115, 115, 122, 101),
            "highlyRated": (300, 105, 90, 105, 115),
            "brandRatings": (205, 110, 108, 105, 110),
            "coverage": (103, 95, 100, 94, 100),
            "completeness": (108, 94, 98, 96, 96, 98),
            "priceBandTable": (153, 96, 109, 109),
        }[name]
        set_object(objects, "columnHeaders", dict(autoSizeColumnWidth=literal("false"),
                                                   columnAdjustment=literal("'fixedWidth'")))
        for item, width in zip(entries, widths):
            set_object(objects, "columnWidth", {"value": literal(f"{width}D")}, {"metadata": item["queryRef"]})
        set_object(objects, "values", dict(wordWrap=literal("false")))
    elif chart == "pivotTable":
        set_object(objects, "columnHeaders", dict(autoSizeColumnWidth=literal("false"),
                                                   columnAdjustment=literal("'fixedWidth'"),
                                                   defaultColumnWidth=literal("101D")))
        set_object(objects, "subTotals", dict(columnSubtotals=literal("false"), rowSubtotals=literal("false")))
    elif chart == "donutChart":
        set_object(objects, "labels", dict(labelDisplayUnits=literal("1D")))
    elif chart in {"clusteredBarChart", "clusteredColumnChart", "scatterChart"}:
        set_object(objects, "valueAxis", dict(labelDisplayUnits=literal("1D")))
        if name == "scatter":
            set_object(objects, "categoryAxis", dict(titleText=literal("'Log10(1 + recorded price)'"),
                                                      showAxisTitle=literal("true")))
            set_object(objects, "valueAxis", dict(titleText=literal("'Rating (0–5)'"),
                                                   showAxisTitle=literal("true")))
            set_object(objects, "dataPoint", dict(fillTransparency=literal("55D")))
    if chart != "textbox":
        set_object(formatting, "padding", dict(top=literal("6D"), bottom=literal("6D"),
                                               left=literal("8D"), right=literal("8D")))


def series(category, *values, group=None, tooltips=()):
    roles = {"Category": [category], "Y": list(values)}
    if group:
        roles["Series"] = [group]
    if tooltips:
        roles["Tooltips"] = list(tooltips)
    return roles


def values(*bindings):
    return {"Values": bindings}


def card(*bindings):
    return {"Data": bindings}


def descending(*bindings):
    return tuple((binding, "Descending") for binding in bindings)


def build_report():
    jsonify(ROOT / "IntelliMarket.pbip", {
        "$schema": f"{FABRIC}/pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0", "artifacts": [{"report": {"path": REPORT.name}}],
        "settings": {"enableAutoRecovery": True},
    })
    jsonify(REPORT / "definition.pbir", {
        "$schema": f"{FABRIC}/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0", "datasetReference": {"byPath": {"path": "../" + MODEL.name}},
    })
    jsonify(DEFINITION / "version.json", {"$schema": f"{REPORT_SCHEMA}/versionMetadata/1.0.0/schema.json", "version": "2.0.0"})
    theme = "IntelliMarket.json"
    base = "CY24SU06"
    jsonify(DEFINITION / "report.json", {
        "$schema": f"{REPORT_SCHEMA}/report/1.0.0/schema.json", "layoutOptimization": "None",
        "themeCollection": {
            "baseTheme": {"name": base, "reportVersionAtImport": "5.52", "type": "SharedResources"},
            "customTheme": {"name": theme, "reportVersionAtImport": "5.52", "type": "RegisteredResources"},
        },
        "resourcePackages": [
            {"name": "SharedResources", "type": "SharedResources",
             "items": [{"name": base, "path": f"BaseThemes/{base}.json", "type": "BaseTheme"}]},
            {"name": "RegisteredResources", "type": "RegisteredResources",
             "items": [{"name": theme, "path": theme, "type": "CustomTheme"}]},
        ],
    })
    jsonify(REPORT / "StaticResources" / "RegisteredResources" / theme, {
        "name": "IntelliMarket", "dataColors": [BLUE, PINK, "#0F766E", "#7C3AED", "#B45309", "#64748B"],
        "background": WHITE, "foreground": NAVY, "tableAccent": BLUE,
        "textClasses": {
            "title": {"fontFace": "Segoe UI Semibold", "fontSize": 13, "color": NAVY},
            "label": {"fontFace": "Segoe UI", "fontSize": 10, "color": NAVY},
            "callout": {"fontFace": "Segoe UI Semibold", "fontSize": 25, "color": NAVY},
        },
    })
    pages = {
        "MarketplaceOverview": ("Marketplace Overview", overview),
        "PriceDiscountAnalytics": ("Price and Discount Analytics", prices),
        "MarketplaceComparison": ("Flipkart vs Myntra", compare),
        "ProductRatingAnalytics": ("Product and Rating Analytics", ratings),
    }
    jsonify(DEFINITION / "pages" / "pages.json", {
        "$schema": f"{REPORT_SCHEMA}/pagesMetadata/1.0.0/schema.json",
        "pageOrder": list(pages), "activePageName": next(iter(pages)),
    })
    for name, (title, configure) in pages.items():
        path = DEFINITION / "pages" / name
        page = {
            "$schema": f"{REPORT_SCHEMA}/page/1.0.0/schema.json", "name": name,
            "displayName": title, "displayOption": "FitToPage", "width": 1600, "height": 900,
            "objects": {"background": properties(color=color("#E9EFF7"), transparency=literal("0D"))},
        }
        plot_types = {}

        def visual(name, chart, *args, **kwargs):
            create_visual(path, name, chart, *args, **kwargs)
            plot_types[name] = chart

        visual("heading", "textbox", None, (16, 16, 544, 48), objects=text_config(title, 22, bold=True))
        visual("navigation", "pageNavigator", None, (568, 16, 856, 48))
        visual("historical", "textbox", None, (16, 768, 1408, 26), objects=text_config(HISTORY, 10))
        configure(visual)
        page["visualInteractions"] = [
            {"source": source, "target": target, "type": "DataFilter"}
            for source, source_type in plot_types.items() if source_type == "slicer"
            for target, target_type in plot_types.items()
            if target_type not in {"slicer", "textbox", "pageNavigator"}
        ]
        jsonify(path / "page.json", page)


def slicers(v, *items):
    width = 280
    for index, (title, binding) in enumerate(items):
        filters = (nonblank(LEAF),) if binding == LEAF else ()
        v(f"slicer{index}", "slicer", title, (16 + index * (width + 12), 74, width, 76), values(binding),
          filters=filters)


def kpis(v, *items):
    for index, (title, measure) in enumerate(items):
        v(f"kpi{index}", "cardVisual", title, (16 + 355 * index, 160, 343, 86), card(measure))


def overview(v):
    slicers(v, ("Marketplace", MARKET), ("Top category", CATEGORY), ("Brand", BRAND))
    kpis(v, ("Catalog listings", "Product Count"), ("Flipkart listings", "Flipkart Products"),
         ("Myntra listings", "Myntra Products"), ("Known brands", "Known Brands"))
    v("marketDonut", "donutChart", "Marketplace distribution", (16, 258, 370, 246),
      {"Category": [MARKET], "Y": ["Product Count"], "Tooltips": ["Marketplace Share"]},
      ((MARKET, "Ascending"),))
    v("topCategories", "clusteredBarChart", "Top 8 categories by listings", (398, 258, 504, 246),
      series(CATEGORY, "Product Count"), descending("Product Count"),
      (top(CATEGORY, "Product Count", 8),))
    v("topBrands", "clusteredBarChart", "Top 8 known brands by listings", (914, 258, 510, 246),
      series(BRAND, "Product Count"), descending("Product Count"),
      (comparison("dim_brand.brand_id", 1, "0L"), top(BRAND, "Product Count", 8, condition=comparison("dim_brand.brand_id", 1, "0L"))))
    v("categoryMarket", "pivotTable", "Category and marketplace distribution", (16, 516, 1408, 240),
      {"Rows": [CATEGORY], "Columns": [MARKET], "Values": ["Product Count"]}, descending("Product Count"))


def prices(v):
    slicers(v, ("Marketplace", MARKET), ("Top category", CATEGORY), ("Recorded price band", BAND))
    kpis(v, ("Average recorded price", "Average Recorded Price"), ("Median recorded price", "Median Recorded Price"),
         ("Average valid Flipkart discount", "Average Valid Discount"), ("Listings with positive discount", "Discounted Products"))
    v("priceDistribution", "clusteredColumnChart", "Product price distribution", (16, 258, 446, 230),
      series(BAND, "Priced Products", group=MARKET))
    v("priceBandTable", "tableEx", "Price bands and median recorded price", (474, 258, 462, 230),
      values(BAND, "Product Count", "Flipkart Median Recorded Price", "Myntra Median Recorded Price"),
      ((BAND, "Ascending"),))
    v("discountBands", "clusteredColumnChart", "Flipkart discount distribution", (948, 258, 476, 230),
      series(f"{FACT}.discount_band", "Discount Eligible Products"),
      filters=(nonblank(f"{FACT}.discount_band"),))
    v("categoryPrice", "clusteredBarChart", "Recorded price by category and marketplace", (16, 500, 590, 256),
      series(CATEGORY, "Median Recorded Price", group=MARKET, tooltips=("Priced Products",)),
      descending("Priced Products"), (top(CATEGORY, "Priced Products", 6),))
    v("topDiscounts", "tableEx", "Top 20 Flipkart discounts", (618, 500, 806, 256),
      values(COMPACT, "Recorded Retail Price", "Recorded Listing Price", "Listing Discount Amount", "Average Valid Discount"),
      descending("Average Valid Discount", "Listing Discount Amount"),
      (comparison(f"{FACT}.discount_fraction", 1, "0D"), top(COMPACT, "Average Valid Discount", 20, condition=comparison(f"{FACT}.discount_fraction", 1, "0D"), tie_break="Listing Discount Amount")))


def compare(v):
    slicers(v, ("Comparison category", LEAF), ("Recorded price band", BAND), ("Top category", CATEGORY))
    v("comparisonScope", "textbox", None, (16, 160, 1408, 35), objects=text_config(
        "Flipkart discounted price • Myntra recorded price • Category labels and dataset coverage differ • No listing identity inferred",
        12))
    v("marketCounts", "clusteredBarChart", "Product listings by marketplace", (16, 207, 446, 232),
      series(MARKET, "Product Count"), ((MARKET, "Ascending"),))
    v("compareBands", "clusteredColumnChart", "Recorded price distribution by marketplace", (474, 207, 462, 232),
      series(BAND, "Priced Products", group=MARKET))
    v("coverage", "tableEx", "Category and brand coverage", (948, 207, 476, 232),
      values(MARKET, "Categories Recorded", "Category Coverage", "Known Brands", "Brand Coverage"))
    v("sharedCategories", "pivotTable", "Mapped categories with recorded prices on both marketplaces",
      (16, 451, 810, 305), {"Rows": [LEAF], "Columns": [MARKET],
                          "Values": ["Comparable Priced Listings", "Comparable Median Price", "Comparable Average Price"]},
      filters=(nonblank(LEAF),))
    v("completeness", "tableEx", "Data completeness by marketplace", (838, 451, 586, 305),
      values(MARKET, "Price Coverage", "Category Coverage", "Brand Coverage", "Rating Coverage", "Attribute Coverage"))


def ratings(v):
    slicers(v, ("Marketplace", MARKET), ("Top category", CATEGORY), ("Brand", BRAND))
    kpis(v, ("Rated listings", "Rated Products"), ("Rating coverage", "Rating Coverage"),
         ("Average recorded rating", "Average Recorded Rating"), ("Listings with a rating count", "Products With Rating Count"))
    v("ratingDistribution", "clusteredColumnChart", "Recorded rating distribution", (16, 258, 392, 230),
      series(f"{FACT}.rating_band", "Rated Products", group=MARKET), filters=(nonblank(f"{FACT}.rating_band"),))
    v("scatter", "scatterChart", "Rating and price density by marketplace", (420, 258, 550, 230),
      {"Category": [f"{FACT}.scatter_bin"], "X": ["Log Recorded Price"], "Y": ["Average Recorded Rating"],
       "Series": [MARKET], "Size": ["Priced Products"],
       "Tooltips": ["Minimum Recorded Price", "Maximum Recorded Price"]},
      filters=(nonblank(f"{FACT}.rating"), nonblank(f"{FACT}.recorded_price")))
    v("missing", "clusteredColumnChart", "Missing rating and attributes", (982, 258, 442, 230),
      series(MARKET, "Missing Rating", "Missing Attributes"))
    v("brandRatings", "tableEx", "Brand ratings and sample sizes", (16, 500, 626, 256),
      values(BRAND, "Average Recorded Rating", "Rated Products", "Product Count", "Rating Coverage"),
      descending("Rated Products"), (comparison("dim_brand.brand_id", 1, "0L"), top(BRAND, "Rated Products", 20, condition=comparison("dim_brand.brand_id", 1, "0L"))))
    v("highlyRated", "tableEx", "Highest ratings with at least 10 reported ratings", (654, 500, 770, 256),
      values(COMPACT, MARKET, "Ranking Rating", "Ranking Rating Count", "Recorded Listing Price"),
      descending("Ranking Rating", "Ranking Rating Count"),
      (nonblank("Ranking Rating"), top(COMPACT, "Ranking Rating", 20, condition=nonblank("Ranking Rating"), tie_break="Ranking Rating Count")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-folder", type=Path, help="Set the initial Desktop parameter value")
    parser.add_argument("--configure-data-folder", type=Path, help="Update only the DataFolder parameter")
    args = parser.parse_args()
    if args.configure_data_folder:
        folder = args.configure_data_folder.resolve(strict=True)
        if not all((folder / f"{name}.csv").is_file() for name in COLUMNS):
            parser.error("The folder must contain the five model CSVs")
        path = TMDL / "expressions.tmdl"
        lines = path.read_text(encoding="utf-8").splitlines()
        index = next(i for i, line in enumerate(lines) if line.startswith("expression DataFolder = "))
        lines[index] = model_path(folder)
        write(path, "\n".join(lines))
    else:
        build_model(args.data_folder)
        build_report()


if __name__ == "__main__":
    main()
