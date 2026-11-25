"""Resolve chatbot assets independently of the process working directory."""

import sqlite3
from pathlib import Path

from .attributes import normalize_value, title_audience


DEFAULT_ROOT = Path(__file__).resolve().parents[1]


def project_root(root=None):
    return Path(root).expanduser().resolve() if root is not None else DEFAULT_ROOT


def catalog_path(root=None, *, catalog=None):
    return (Path(catalog).expanduser().resolve() if catalog is not None
            else project_root(root) / "artifacts" / "catalog.sqlite3")


def index_path(root=None, *, index_dir=None):
    return (Path(index_dir).expanduser().resolve() if index_dir is not None
            else project_root(root) / "artifacts" / "semantic")


def open_catalog(path):
    catalog = Path(path).expanduser().resolve()
    try:
        connection = sqlite3.connect(catalog.as_uri() + "?mode=ro", uri=True)
    except sqlite3.OperationalError as error:
        raise sqlite3.OperationalError(
            f"Cannot open SQLite catalog at {catalog}. Verify the path and Windows read permissions. "
            f"SQLite reported: {error}"
        ) from error
    connection.row_factory = sqlite3.Row
    connection.create_function("rag_attribute", 1, normalize_value, deterministic=True)
    connection.create_function("rag_title_audience", 2, title_audience, deterministic=True)
    return connection
