# IntelliMarket dashboard handover

## Open and refresh in Power BI Desktop

Use a current Windows Power BI Desktop build. Keep IntelliMarket.pbip, IntelliMarket.Report and IntelliMarket.SemanticModel together. From the repository root in PowerShell, configure the existing CSV folder before opening the project.

~~~powershell
python -B powerbi/scripts/build_project.py --configure-data-folder powerbi/data
Start-Process -FilePath (Resolve-Path -LiteralPath powerbi/IntelliMarket.pbip).Path
~~~

On the original workstation, the available interpreter was the Python executable under rag_chatbot/.venv. If python is unavailable on PATH, substitute .\rag_chatbot\.venv\Scripts\python.exe. The command uses only the standard library. It updates just the TMDL DataFolder parameter, leaving visual and model edits intact. Re-run it after moving the repository. The project as delivered contains a path placeholder.

If file association is unavailable, start Desktop and use File > Open > Browse. If the file type is hidden, enable Power BI Project (.pbip) in File > Options and settings > Options > Preview features, and enable the enhanced report format option if the build lists one. Restart Desktop. On first open, select Home > Refresh and choose the local data source privacy level appropriate to the machine. After a move, it is also possible to set DataFolder using Transform data > Edit Parameters. No chatbot process is needed.

On the first Desktop run, verify 34,220 total listings, flip the marketplace slicer and confirm 19,998 and 14,222. Check the price-band sort, scope colors and the nine comparable categories. Verify the scatterplot shows price-and-rating density bubbles and that the ranking table obeys the rating-count threshold. Select a slicer and a chart data point, then test page navigation.

## Recovery

1. For a path or source error, close Desktop, run the configure command with an existing folder containing the five model CSVs and reopen. Inside Desktop, check DataFolder and each query's source. Use UTF-8, comma delimiters and English (United States) for decimal conversion. Refresh after changing the parameter.
2. For an entry-file error, open IntelliMarket.Report/definition.pbir directly from Desktop or Explorer. Its relative byPath reference loads IntelliMarket.SemanticModel from the sibling directory. If Desktop rejects the report format, update to a Desktop build with enhanced PBIR support, enable the available project options and restart. For a path-length error, copy the whole powerbi folder to a shorter local path and configure its CSV folder.
3. To recover the model in a fresh Desktop file, use the five imports and explicit types in [Desktop import instructions](DESKTOP.md). Create four single-direction relationships using the [star schema](../model/STAR_SCHEMA.md). In Data or Model view, create the calculated columns from [Dashboard DAX](../model/DASHBOARD_DAX.md) in the order shown, then create and format the measures. Sort price_band by price_band_id, rating_band by rating_band_order, and discount_band by discount_band_order.
4. To recover the report manually, set the canvas to 1600 × 900 on four pages, use View > Themes > Browse for themes to import IntelliMarket.Report/StaticResources/RegisteredResources/IntelliMarket.json, and use Insert > Buttons > Navigator > Page navigator. Recreate charts from the [visual bindings](../reports/VISUAL_BINDINGS.md). For Top N, use the visual-level Filters pane, set the category or listing filter to Top N, and add the ordering measure. For the comparison matrix, exclude blank comparison categories and use the three Comparable measures. For the high-rating table, filter Ranking Rating to is not blank before ranking. Add slicer interactions via Format > Edit interactions and copy the historical text to each page. Save your recovered report in a Desktop-supported format. There is no generated PBIX file.

## Model and validation

- Five imported tables use typed Power Query CSV partitions. The four dimensions filter fact_product through active single-direction one-to-many relationships. Source lineage remains available as a separate audit CSV.
- The project uses the documented PBIP and PBIR envelopes, enhanced per-visual JSON, and the semantic model's TMDL definition. All 67 project JSON files passed Microsoft public schema validation, including the theme. Microsoft Tabular Object Model 19.120.1 deserialized the TMDL with four active one-direction relationships, five tables and 29 measures.
- Eight automated tests passed. The checks cover table paths, relationship endpoints, report references, visual bindings and layout bounds, slicer interactions, unique listings, dimensions, lineage and independently calculated KPI values. Desktop was not detected. UI rendering, refresh, DAX engine execution and keyboard or pointer interactions remain unverified.
- To test again, run python -B -m unittest discover -s powerbi/tests -v. Optional JSON schema validation uses jsonschema 4.x and network access to the Microsoft URLs. Run python -B powerbi/scripts/validate_schemas.py from a Python environment with that dependency. Optional TMDL checking uses PowerShell 7 with the Microsoft.AnalysisServices NuGet package's lib/net8.0 directory. Run ./powerbi/scripts/validate_tmdl.ps1 -AssemblyDirectory followed by that directory.

References [PBIP project format](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-overview) · [Enhanced PBIR](https://learn.microsoft.com/en-us/power-bi/developer/embedded/projects-enhanced-report-format) · [TMDL parser and format](https://learn.microsoft.com/en-us/analysis-services/tmdl/tmdl-overview) · [Microsoft theme schemas](https://github.com/microsoft/powerbi-desktop-samples/tree/main/Report%20Theme%20JSON%20Schema)

See [Phase 10 corrections and verification](PHASE10.md).
