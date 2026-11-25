# Power BI Desktop import and Phase 9 formats

No Power BI Desktop installation was detected through executable discovery, the usual Program Files and WindowsApps locations, Appx packages, Start menu entries or Windows uninstall registry entries. Desktop import, DAX execution and actual project format creation remain unverified on this workstation.

- PBIP is the project entry file for separate report and semantic model folders. Microsoft documents PBIP save as a preview option in Desktop. Check File > Options and settings > Options > Preview features on the Desktop build used for Phase 9. [Microsoft PBIP documentation](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-overview)
- PBIR is the enhanced report format. Its JSON separates pages, visuals and bookmarks. Check enhanced-format availability and the saved structure on the installed Desktop build. [Microsoft PBIR documentation](https://learn.microsoft.com/en-us/power-bi/developer/embedded/projects-enhanced-report-format)
- TMDL describes the semantic model. Desktop TMDL view is generally available, and a PBIP semantic model using TMDL stores its definition in the semantic model folder. [Microsoft TMDL view](https://learn.microsoft.com/en-us/power-bi/transform-model/desktop-tmdl-view) · [Semantic model project folder](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-dataset)

## Import

1. In Desktop select Get data > Text/CSV for the fact and four dimension CSVs. Use comma delimiter, first-row headers and UTF-8 code page 65001. Set types in Power Query using the dictionary. Use a decimal-dot locale such as English (United States) for number conversions, independently of currency. Preserve source IDs as text and empty numeric cells as null.
2. Parameterise the folder in Power Query as DataFolder and use it to build each source path. Update that parameter when moving the repository. Keep table names equal to CSV stems so the DAX references resolve.
3. Turn off automatic relationship detection for this file, or remove auto-detected relationships. Create just the four active, single-direction links in the model specification. Disable automatic date hierarchies if applicable. Keep source_lineage outside the star and load it only for audit.
4. Hide technical keys where appropriate. Set price_band to Sort by column price_band_id. Set price and rating columns to Don't summarize as a default, and add explicit measures. Check totals for both marketplace filters against the reconciliation table.
5. Refresh after regeneration completes. Phase 9 can use PBIP with PBIR and TMDL if enabled on the target Desktop build. Save a local PBIX if project-format authoring is unavailable.
