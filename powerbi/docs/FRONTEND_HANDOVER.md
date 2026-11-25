# IntelliMarket analytics frontend handover

Use one interactive Power BI report for Marketplace Overview, Price and Discount Analytics, Flipkart vs Myntra, and Product and Rating Analytics. The local PBIP has already passed manual Desktop inspection. The examples below await an embed URL from a selected Power BI Service workspace.

## Choose how viewers will sign in

| Option | Audience and requirements |
|---|---|
| Secure iframe | Recommended for the project team or an examiner who can sign in with an authorized organizational account. Grant report access in Power BI first. Viewers usually need Pro or PPU. A qualifying Premium capacity or Fabric F64+ can cover eligible free viewers when both the report and model are hosted there. PPU workspaces require PPU for consumers. Verify the intended account type and tenant policies. |
| Publish to web | Anyone on the internet can view the report without an account, including underlying detail-level model data. Requires an enabled tenant setting, creation rights, and an eligible publishing license. Microsoft lists a Power BI license for My Workspace and Pro or PPU for shared workspaces. Use only after explicit approval and clearance to redistribute the imported data. |
| JavaScript SDK, user owns data | Use when the website needs controlled navigation, render/error events, or custom filter UI for signed-in viewers. Register an Entra application, obtain a delegated token, and honor Power BI report permissions and viewer licensing. Pro/PPU or qualifying capacity rules apply. |
| JavaScript SDK, app owns data | Use when website users should access the report without Microsoft sign-in. Requires an authenticated website backend, an authorized Entra service principal or other supported embedding identity, and a supported production embedding capacity. Viewers do not need per-user Power BI licenses in this mode. The backend authorizes access and issues short-lived embed tokens. |

Use a work or school Microsoft Entra account when publishing to the organization tenant. For a shared project workspace, confirm that the publisher has an eligible Pro or PPU license and an edit-capable workspace role such as Contributor, and that the tenant allows the chosen option. Check examiner access with their actual account before the demonstration. A secure iframe's auto-auth URL cannot be repurposed as SDK authentication. [Secure embedding](https://learn.microsoft.com/en-us/power-bi/collaborate-share/service-embed-secure) · [Power BI embed tokens](https://learn.microsoft.com/en-us/power-bi/developer/embedded/embed-tokens) · [Capacity and licensing](https://learn.microsoft.com/en-us/power-bi/developer/embedded/embedded-capacity)

## Publish the existing report to a restricted workspace

1. Manually open powerbi/IntelliMarket.pbip in Power BI Desktop. Keep its report and semantic-model folders beside it. If the repository moved, update DataFolder using the [Desktop handover](DASHBOARD.md).
2. Select Home → Refresh. Confirm 34,220 total listings, 19,998 Flipkart and 14,222 Myntra. Check the comparison matrix and all four page tabs.
3. Select Home → Publish, or File → Publish → Publish to Power BI. Sign in privately. Select the intended restricted workspace and click Select. If Desktop offers to replace an existing report or model, verify that the workspace and existing item are the intended targets first.
4. Open the success link. In the workspace, verify that the report and semantic model both exist. Open the report in Power BI Service, check all four pages again, then grant named test viewers access through Share or Manage permissions as appropriate.
5. Confirm the release intent before enabling any public sharing. Desktop publish deploys the imported catalog data with the report. For this snapshot, refresh from the local CSVs in Desktop and republish to update it. For scheduled refresh, configure an authorized gateway or move to an approved cloud source and update the semantic model. The Service cannot automatically read this workstation's local CSV path. [PBIP deployment](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-overview) · [Publish with Desktop](https://learn.microsoft.com/en-us/power-bi/create-reports/desktop-upload-desktop-files)

### Secure iframe

1. Open the published report in the Service. Select File → Embed report → Website or portal. Copy the secure URL, typically https://app.powerbi.com/reportEmbed?reportId=REPLACE_REPORT_ID&autoAuth=true plus any Service-provided query parameters.
2. Visit each of the four pages in the Service. In each browser URL, read the page ID after the report ID. Use the Service IDs, which can differ from display titles. Set VITE_PBI_MODE=secure, VITE_PBI_EMBED_URL and the four ID settings in the example. It appends the documented pageName parameter and retains all other URL parameters.
3. Test as an authorized viewer and as a viewer without access in a separate browser session. Use the open-in-Power-BI link for first-time sign-in or when browser iframe restrictions interfere. A URL filter or hidden page is for display; access control comes from report permissions and, if applicable, RLS or OLS. [Secure iframe instructions](https://learn.microsoft.com/en-us/power-bi/collaborate-share/service-embed-secure)

### Public iframe, only after explicit approval

1. Review dataset redistribution terms, tenant policy and all imported model detail. The current model contains prices, ratings, brands, source IDs and other product-level fields. Assume underlying data can be accessed, copied and shared. Page hiding, embedding on a protected website and removing visual export controls do not make a public link private.
2. After approval, in the Service choose File → Embed report → Publish to web (public). Select Create embed code, review Microsoft's public disclosure warning, then select Publish. Choose a default page and copy the generated /view?r=... URL. If the option is missing, check with the tenant admin rather than trying to bypass the setting.
3. Set mode to public and use the generated URL. Keep the report's existing page navigator for the four pages. The optional per-page URL settings accept only links supplied and verified for this report. Microsoft permits one public embed code per report. The example does not construct undocumented public page deep links.
4. Verify from a signed-out browser and check all report pages. To revoke the embed, remove its code in Service Settings → Manage embed codes. Revocation cannot recall data already copied. [Publish to web instructions and limitations](https://learn.microsoft.com/en-us/power-bi/collaborate-share/service-publish-to-web)

## Integrate the React example

The standalone example is in [frontend_example](../frontend_example/). To run it later in a development environment where installing dependencies is permitted:

~~~powershell
Set-Location powerbi/frontend_example
Copy-Item .env.example .env.local
npm install
npm run dev
~~~

Use a Vite-compatible Node version. Placeholder mode renders a setup message without loading an iframe. Restart Vite after editing .env.local. All VITE_ settings are public client configuration. Never put tokens or credentials there.

For the website, copy Analytics.mjs, config.mjs and analytics.css into the frontend partner's codebase and render Analytics on the analytics route. Use the site's existing configuration mechanism. The sample main.mjs is only the standalone entry point.

~~~js
import React from "react";
import { Analytics } from "./Analytics.mjs";

export function AnalyticsPage({ analyticsConfig }) {
  return React.createElement(Analytics, { config: analyticsConfig });
}
~~~

Use a trusted static configuration for mode, url and pageNames or pageUrls. For the standard commercial tenant, allow https://app.powerbi.com in the site's frame-src policy and use HTTPS in deployment. The example accepts standard commercial Power BI URLs. Sovereign-cloud deployments require a reviewed host allowlist change. The 16:9 frame includes a minimum height, responsive navigation, a fullscreen button and a direct Power BI link. Test a narrow viewport, keyboard navigation and browser fullscreen support. Add vertical space if Power BI's own footer crowds the canvas.

The iframe's load event confirms that the frame navigated. The parent page cannot inspect a cross-origin sign-in screen or reliably distinguish report rendering from an error served inside that frame. The example provides a loading status, slow-load message, reload and direct-open recovery. A secure page-button switch reloads the iframe and may reset filters. The native report navigator avoids remounting the iframe.

### Optional SDK integration

The [SDK adapter](../frontend_example/sdk.mjs) accepts a Power BI JavaScript client Service, a container and a correctly authorized embed configuration. The host chooses models.TokenType.Aad for user-owned data or models.TokenType.Embed for app-owned data. Obtain an SDK-compatible embed URL and report ID from the selected SDK flow. Supply the token at runtime. Never store tokens, client secrets or service principal credentials in browser configuration or logs.

Mount the adapter in a React effect. Set loading state before mounting, clear it on onRendered, show a generic recovery message in onError, and populate navigation from onPages. Call navigate(page.name) on a button click, fullscreen() from a click handler and dispose() during cleanup. Handle rejected navigation promises in the host. Refresh tokens through the authorized authentication flow and pass them to refreshToken before expiration. Keep app-owned token generation and access checks on the backend. [SDK navigation](https://learn.microsoft.com/en-us/javascript/api/overview/powerbi/page-navigation) · [SDK events](https://learn.microsoft.com/en-us/javascript/api/overview/powerbi/handle-events) · [Embedding flows](https://learn.microsoft.com/en-us/power-bi/developer/embedded/embed-tokens)

## Local alternative for a later phase

If the organization cannot publish to Power BI Service, keep the same Analytics route and build the four views from the validated Power BI CSV exports. A website-owned backend could serve approved aggregates and filtered listing drill-down, using the existing star grain, coverage rules and historical disclaimers. Expose only data the site is authorized to distribute. Preserve all four pages and validate outputs against the existing SQLite benchmarks. This alternative is a plan. No local analytics backend or charts are included.

## Acceptance checks once an embed URL exists

- Check all four page titles, slicers and cross-filtering. Confirm 34,220 listings and the nine comparable categories.
- Check slow and blocked loads, a signed-out or unauthorized secure viewer, fullscreen, the direct-opening link and mobile width.
- Display the historical dataset notice beside the report. The Flipkart crawl dates to 2015–2016. Myntra's observation date and currency are unspecified. Current prices and availability are unverified.
