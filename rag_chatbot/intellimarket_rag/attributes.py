"""Positive catalog attribute constraints, distinct from keyword evidence."""

import re
import unicodedata
from functools import lru_cache


FABRICS = {
    "cotton": ("cotton", "pure cotton", "100 cotton", "100 cotton woven", "organic cotton",
               "cotton jersey", "cotton hosiery", "single jersey cotton"),
    "pure cotton": ("pure cotton", "100 cotton", "100 cotton woven"),
    "cotton blend": ("cotton blend", "cotton mix", "cotton lycra", "cotton lycra blend",
                     "lycra cotton", "cotton spandex", "cotton polyester", "poly cotton",
                     "polycotton", "polyester cotton", "cotton polyester blend", "cotton silk", "cotton silk blend"),
    "cotton lycra": ("cotton lycra", "cotton lycra blend", "lycra cotton", "cotton spandex",
                     "spandex cotton", "70 cotton30 lycra", "70 cotton 30 lycra"),
    "cotton silk": ("cotton silk", "cotton silk blend", "silk cotton"),
    "cotton polyester": ("cotton polyester", "polyester cotton", "polycotton", "poly cotton",
                         "cotton polyester blend"),
    "modal": ("modal", "pure modal", "100 modal"),
    "rayon": ("rayon", "viscose rayon", "viscose", "pure rayon"),
    "linen": ("linen", "pure linen", "100 linen"),
    "silk": ("silk", "pure silk", "100 silk"),
    "polyester": ("polyester", "pure polyester", "100 polyester"),
    "nylon": ("nylon", "100 nylon"),
    "wool": ("wool", "pure wool", "100 wool"),
    "poly crepe": ("poly crepe", "polyester crepe"),
    "denim": ("denim", "cotton denim"),
    "net": ("net",),
}
MATERIALS = {
    "leather": ("leather", "genuine leather", "pure leather", "100 leather"),
    "synthetic leather": ("synthetic leather", "faux leather", "artificial leather"),
    "stainless steel": ("stainless steel",),
    "ceramic": ("ceramic",),
    "solid wood": ("solid wood",),
    "mesh": ("mesh",),
}
GENDERS = {
    "women": ("women", "women s", "woman", "female", "ladies"),
    "men": ("men", "men s", "man", "male", "gents"),
    "girls": ("girls", "girl", "girl s", "girls s"),
    "boys": ("boys", "boy", "boy s", "boys s"),
    "unisex": ("unisex",),
}
PATTERNS = {
    "floral": ("floral", "floral print", "floral printed", "floral prints"),
    "solid": ("solid", "plain"),
    "striped": ("striped", "stripe", "stripes"),
    "checked": ("checked", "checks", "checkered"),
    "printed": ("printed", "print"),
}
OCCASIONS = {name: (name,) for name in ("casual", "formal", "festive", "party", "sports")}
CLOSURES = {
    "snap button": ("snap button", "snap buttons"),
    "button": ("button", "buttons", "button closure", "snap button", "snap buttons"),
    "zip": ("zip", "zipper", "zip closure"),
    "slip on": ("slip on", "slip-on"),
    "drawstring": ("drawstring", "draw string"),
}
FACETS = {
    "fabric": (FABRICS, ("fabric", "kurta fabric", "top fabric", "saree fabric", "lehenga fabric")),
    "bottom_fabric": (FABRICS, ("bottom fabric",)),
    "material": (MATERIALS, ("material", "body material", "outer material", "primary material",
                             "upper material", "frame material", "base material", "fabric")),
    "gender": (GENDERS, ("gender", "ideal for")),
    "pattern": (PATTERNS, ("pattern", "print or pattern type", "top pattern")),
    "occasion": (OCCASIONS, ("occasion",)),
    "closure": (CLOSURES, ("closure", "fastening type", "top closure")),
}
COLOURS = ("navy blue", "lime green", "off white", "black", "blue", "white", "red", "green",
           "pink", "grey", "gray", "brown", "yellow", "orange", "purple", "beige",
           "maroon", "olive", "multicolour", "multicolor")
APPAREL = (r"kurtas?|kurtis?|shirts?|t[ -]?shirts?|tops?|clothing|clothes|dresses?|jeans|jackets?|"
           r"shorts|sarees?|lehenga(?:s)?|palazzos|trousers|leggings|ponchos?|socks|bras?|outfits?|ones?")
ITEM = APPAREL + r"|bags?|backpacks?|shoes?|sneakers?|sandals?|belts?|bottles?|mugs?|curtains?"
MODIFIERS = r"(?:[\w]+[ -]+){0,6}"


class AttributeConstraintError(ValueError):
    pass


def normalize_value(value):
    if not isinstance(value, str):
        return ""
    return _normalize_text(value)


@lru_cache(maxsize=8192)
def _normalize_text(value):
    return " ".join(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", value).casefold()))


def canonical_facet(field, value):
    terms = FACETS[field][0]
    value = normalize_value(value)
    # Canonical names take precedence when a broader filter includes a narrower one.
    if value in terms:
        return value
    if terms is FABRICS:
        if value in {"100 cotton", "100 cotton woven", "purely cotton"}:
            return "pure cotton"
        for component in ("cotton lycra", "cotton silk", "cotton polyester"):
            if value in FABRICS[component]:
                return component
    for name, aliases in terms.items():
        if value in aliases:
            return name
    raise AttributeConstraintError(f"Unsupported {field.replace('_', ' ')} value. Use a supported catalog attribute.")


def alternation(values):
    return "|".join(re.escape(value) for value in sorted(values, key=len, reverse=True))


def extract_attributes(text):
    t = text.casefold().replace("’", "'")
    # Brand mentions are contextual evidence. A brand qualifier binds only in typed syntax.
    source = re.sub(r"\b(?:cotton fab|cotton world|cotton culture)\b", " ", t)
    facets = {}

    def put(field, value):
        if field in facets and facets[field] != value:
            raise AttributeConstraintError(
                f"Choose one {field.replace('_', ' ')} value, or use an explicit semicolon filter."
            )
        facets[field] = value

    fibres = alternation(FABRICS)
    materials = alternation(MATERIALS)
    atoms = fibres + "|" + materials + "|" + alternation(COLOURS) + "|" + alternation(GENDERS)
    if re.search(rf"\b(?:{atoms})\b(?:\s+(?:or|and|except)\s+|\s*[,&]\s*)(?:{atoms})\b|"
                 rf"\b(?:{atoms})\b\s+or\s+\w+|\b\w+\s+or\s+(?:{atoms})\b|"
                 rf"\b(?:not|without|except|non[- ])\s*(?:(?:made from|made of|any)\s+)?"
                 rf"(?:{atoms})\b|\b(?:{atoms})-free\b", source):
        raise AttributeConstraintError("Choose a single positive attribute or state the exact blend.")

    explicit_fibres = (r"100\s*%\s*cotton|purely cotton|cotton[ -]blend|"
                       r"cotton[ /-](?:lycra|silk|polyester)(?: blend)?|" + fibres)
    consumed = []
    for match in re.finditer(rf"\b({explicit_fibres})\b(?=\s+palazzos\b)", source):
        if re.search(r"\b(?:with|includes?|and)\s+(?:\w+\s+){0,2}$", source[:match.start()]):
            put("bottom_fabric", canonical_facet("bottom_fabric", match[1]))
            consumed.append(match.span())
    for start, end in reversed(consumed):
        source = source[:start] + " " * (end - start) + source[end:]
    for match in re.finditer(rf"\b({explicit_fibres})\b", source):
        before, after = source[:match.start()], source[match.end():]
        # Denim is a product style in catalog titles. Treat it as a fabric only when explicitly requested.
        explicit = (re.search(r"\b(?:made (?:from|of)|(?:fabric|material)(?: is)?|in)\s*$", before)
                    or re.match(r"\s+(?:fabric|material)\b", after))
        leading = re.match(rf"\s+{MODIFIERS}(?:{APPAREL})\b", after)
        if explicit or (leading and match[1] not in {"denim", "net"}):
            put("fabric", canonical_facet("fabric", match[1]))
    for match in re.finditer(rf"\b({materials})\b", source):
        before, after = source[:match.start()], source[match.end():]
        if (re.search(r"\b(?:made (?:from|of)|material(?: is)?)\s*$", before)
                or re.match(rf"\s+(?:material\b|{MODIFIERS}(?:{ITEM})\b)", after)):
            put("material", canonical_facet("material", match[1]))
    if not ({"fabric", "bottom_fabric", "material"} & facets.keys()) and re.search(
            r"\b(?:made from|made of|fabric is|material is)\s+\w+", source):
        raise AttributeConstraintError("Specify a supported fabric or material using a semicolon filter.")

    for match in re.finditer(rf"\b({alternation(COLOURS)})\b(?=\s+{MODIFIERS}(?:{ITEM})\b|\s*$)", source):
        put("colour", "grey" if match[1] == "gray" else match[1])
    for name, aliases in GENDERS.items():
        variants = aliases + tuple(value.replace(" s", "'s") for value in aliases if value.endswith(" s"))
        option = alternation(variants)
        if re.search(rf"\b(?:for\s+(?:{option})\b|(?:{option})\b(?=\s+{MODIFIERS}(?:{APPAREL})\b|\s*$))", source):
            put("gender", name)
    for pattern in PATTERNS:
        if re.search(rf"\b{pattern}\s+(?:print|pattern)s?\b", source):
            put("pattern", pattern)
    for occasion in OCCASIONS:
        if re.search(rf"\b(?:occasion\s+(?:is\s+)?{occasion}|{occasion}\s+occasion)\b", source):
            put("occasion", occasion)
    closure = re.search(r"\b(snap buttons?|button|zipper?|slip[ -]on|drawstring) closure\b|\bwith (snap buttons?)\b", source)
    if closure:
        put("closure", canonical_facet("closure", closure[1] or closure[2]))
    return facets


def attribute_sql(field, value):
    terms = FACETS[field][0]
    keys = facet_keys(field, value)
    aliases = terms[canonical_facet(field, value)]
    placeholders = ",".join("?" for _ in aliases)
    # Select the primary recorded field. Components such as linings cannot satisfy a main-fabric filter.
    extracts = [f'''json_extract(p.attributes, '$."{key}"')''' for key in keys]
    data = extracts[0] if len(extracts) == 1 else "coalesce(" + ",".join(extracts) + ")"
    conflict_keys = ",".join("?" for _ in keys)
    predicate = f"""NOT EXISTS (SELECT 1 FROM json_each(p.conflicts) conflict
                        WHERE conflict.key IN ({conflict_keys}))
                   AND (SELECT count(*) > 0 AND min(rag_attribute(value) IN ({placeholders}))
                        FROM json_each({data}))"""
    parameters = [f"attributes.{key}" for key in keys] + list(aliases)
    if field == "pattern" and value != "printed":
        incompatible = [alias for name, category in PATTERNS.items() if name not in {value, "printed"}
                        for alias in category]
        exclusion = ",".join("?" for _ in incompatible)
        predicate += f""" AND NOT EXISTS (
            SELECT 1 FROM json_each(json_extract(p.attributes, '$.pattern'))
            WHERE rag_attribute(value) IN ({exclusion}))"""
        parameters.extend(incompatible)
    if field == "gender":
        # Some Myntra rows have an explicit audience label in their source title, but no audience field.
        predicate = f"""({predicate}) OR (
            p.platform='myntra' AND {data} IS NULL
            AND NOT EXISTS (SELECT 1 FROM json_each(p.conflicts) conflict
                            WHERE conflict.key IN ('attributes.gender','attributes.ideal for','name'))
            AND rag_title_audience(p.name,p.brand)=?)"""
        parameters.append(value)
    return "(" + predicate + ")", parameters


def facet_keys(field, value):
    if field == "pattern" and value != "printed":
        return ("print or pattern type", "pattern", "top pattern")
    return FACETS[field][1]


def title_audience(title, brand):
    value, brand = normalize_value(title), normalize_value(brand)
    # Myntra titles often start with a recorded brand followed by an audience label.
    if not brand or not value.startswith(brand + " "):
        return None
    value = value[len(brand) + 1:]
    found = {name for name, aliases in GENDERS.items()
             if any(f" {alias} " in f" {value} " for alias in aliases)}
    if len(found) != 1:
        return None
    category, = found
    return category if any(value == alias or value.startswith(alias + " ")
                           for alias in GENDERS[category]) else None
