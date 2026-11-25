"""Validate PBIP/PBIR files against the Microsoft schemas declared in them."""
import json
from functools import lru_cache
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError

from jsonschema import Draft7Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

ROOT = Path(__file__).resolve().parents[1]
THEME_SCHEMA = ("https://raw.githubusercontent.com/microsoft/powerbi-desktop-samples/main/"
                "Report%20Theme%20JSON%20Schema/reportThemeSchema-2.159.json")
DESKTOP_FALLBACKS = {
    "visualContainer/2.15.0/": "visualContainer/2.13.0/",
    "report/3.4.0/": "report/3.3.0/",
}


@lru_cache
def retrieve(uri):
    with urlopen(uri, timeout=20) as stream:
        return Resource.from_contents(json.load(stream), default_specification=DRAFT7)


def main():
    registry = Registry(retrieve=retrieve)
    documents = [ROOT / "IntelliMarket.pbip", ROOT / "IntelliMarket.SemanticModel/definition.pbism",
                 ROOT / "IntelliMarket.Report/definition.pbir",
                 *sorted(path for path in (ROOT / "IntelliMarket.Report").rglob("*.json")
                         if ".pbi" not in path.relative_to(ROOT).parts)]
    failures = []
    fallbacks = {}
    for path in documents:
        instance = json.loads(path.read_text(encoding="utf-8"))
        schema = instance.get("$schema", THEME_SCHEMA)
        try:
            retrieve(schema)
        except HTTPError as error:
            if error.code != 404:
                raise
            replacement = next((schema.replace(old, new) for old, new in DESKTOP_FALLBACKS.items()
                                if old in schema), None)
            if replacement is None:
                raise
            fallbacks[schema] = replacement
            # Keep the Desktop document intact and validate its content against
            # the closest published schema, including that version's $schema.
            instance["$schema"] = schema = replacement
            if "/report/3.3.0/" in schema:
                sync_version = instance.pop("linguisticSchemaSyncVersion", None)
                if sync_version is not None:
                    print(f"{path.relative_to(ROOT)}: preserved Desktop-only linguisticSchemaSyncVersion; "
                          "the compatibility schema does not cover it.")
        validation = Draft7Validator({"$ref": schema}, registry=registry)
        for error in validation.iter_errors(instance):
            location = "/".join(str(part) for part in error.absolute_path)
            failures.append(f"{path.relative_to(ROOT)} {location}: {error.message}")
    if failures:
        raise SystemExit("\n".join(failures))
    print(f"Validated {len(documents)} JSON files against Microsoft public schemas.")
    for original, replacement in fallbacks.items():
        print(f"Compatibility check only (declared schema returned 404): {original} -> {replacement}")


if __name__ == "__main__":
    main()
