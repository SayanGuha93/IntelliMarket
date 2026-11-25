import json
import sqlite3
import subprocess
import sys
import unittest
from contextlib import closing
from pathlib import Path

from intellimarket_rag.chat import Chatbot
from intellimarket_rag.paths import catalog_path, index_path, open_catalog, project_root
from intellimarket_rag.semantic import active_index, catalog_identity, validate_index


ROOT = Path(__file__).resolve().parents[1]


class PathResolutionTests(unittest.TestCase):
    def run_search(self, cwd, entry_point, *extra):
        result = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", *entry_point, "search",
             "--product-id", "17685166", "--platform", "myntra", *extra],
            cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)[0]["source_id"], "17685166")

    def test_search_from_repository_root_uses_module_assets(self):
        self.run_search(ROOT.parent, ["rag_chatbot/run_chatbot.py"])

    def test_module_command_from_chatbot_directory(self):
        self.run_search(ROOT, ["-m", "intellimarket_rag"])

    def test_explicit_root_and_catalog_override_use_caller_relative_paths(self):
        self.run_search(ROOT.parent, ["rag_chatbot/run_chatbot.py"],
                        "--root", "rag_chatbot/evaluation", "--catalog", "rag_chatbot/artifacts/catalog.sqlite3")
        self.assertEqual(project_root(), ROOT)

    def test_explicit_index_and_catalog_match_existing_active_manifest(self):
        catalog = ROOT / "artifacts" / "catalog.sqlite3"
        index = ROOT / "artifacts" / "semantic"
        separate_root = ROOT / "evaluation"
        with closing(open_catalog(catalog_path(separate_root, catalog=catalog))) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM products").fetchone()[0], 34220)
        selected, manifest = active_index(separate_root, index_dir=index)
        self.assertEqual(selected.parent, index_path(index_dir=index))
        self.assertEqual(manifest["catalog_sha256"],
                         catalog_identity(separate_root, catalog=catalog)["catalog_sha256"])
        self.assertEqual(validate_index(selected, manifest).count_rows(), manifest["vector_count"])
        bot = Chatbot(separate_root, catalog=catalog, index_dir=index)
        self.assertEqual(bot.retrieval.catalog, catalog)
        self.assertEqual(bot.retrieval.index_dir, index)

    def test_missing_catalog_reports_path_and_never_creates_a_file(self):
        absent = ROOT / "artifacts" / "missing-path-regression.sqlite3"
        with self.assertRaises(sqlite3.OperationalError) as error:
            open_catalog(absent)
        self.assertIn(str(absent), str(error.exception))
        self.assertFalse(absent.exists())
