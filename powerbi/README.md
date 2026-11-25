# IntelliMarket Power BI data preparation

This standalone module uses Python 3.10+ and its standard library. The input is the existing SQLite catalog, opened with mode=ro. The exported CSVs can be imported without Python, SQLite, the chatbot server, Gemini or LanceDB.

| Path | Purpose |
|---|---|
| data/ | Six UTF-8 CSV exports with BOM |
| scripts/ | Reproducible catalog exporter |
| model/ | Star schema, column dictionary and proposed DAX |
| reports/ | Dashboard page specifications |
| tests/ | Independent SQLite-to-CSV reconciliation |
| docs/ | Power BI Desktop import and format notes |

## Regenerate and validate

From the IntelliMarket root in PowerShell with a standard Python installation:

~~~powershell
python -B powerbi/scripts/export_catalog.py
python -B -m unittest discover -s powerbi/tests -v
~~~

On this workstation the existing Python executable was used because the Windows launcher reported no installed Python. The exporter itself imports only standard-library modules.

~~~powershell
.\rag_chatbot\.venv\Scripts\python.exe -B powerbi/scripts/export_catalog.py
.\rag_chatbot\.venv\Scripts\python.exe -B -m unittest discover -s powerbi/tests -v
~~~

The default source and destination are resolved relative to the script. Use --catalog for another compatible catalog and --output for a subdirectory inside powerbi/data. To reconcile a replacement source exported to the default destination, set POWERBI_TEST_CATALOG to that path before running the tests. Regenerate all CSVs as a set and refresh Desktop after the export completes. Dimension IDs are generated per snapshot.

See [model and dictionary](model/STAR_SCHEMA.md), [DAX proposals](model/MEASURES.md), [page specifications](reports/PAGE_PLAN.md), and [Desktop import and compatibility](docs/DESKTOP.md).

## Editable dashboard

Phase 9 delivers IntelliMarket.pbip with its report and semantic model folders. Configure the DataFolder parameter before opening. See [dashboard handover](docs/DASHBOARD.md), [implemented DAX](model/DASHBOARD_DAX.md) and [visual bindings](reports/VISUAL_BINDINGS.md).
