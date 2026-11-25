import test from "node:test";
import assert from "node:assert/strict";
import { pageLinks, pages } from "./config.mjs";
import { mountSdkReport } from "./sdk.mjs";

test("secure mode sets four page names and preserves the original query", () => {
  const pageNames = Object.fromEntries(pages.map(({ key }) => [key, "Page " + key]));
  const links = pageLinks({ mode: "secure", url: "https://app.powerbi.com/reportEmbed?reportId=example&autoAuth=true", pageNames });
  for (const { key } of pages) {
    const url = new URL(links[key]);
    assert.equal(url.searchParams.get("pageName"), pageNames[key]);
    assert.equal(url.searchParams.get("autoAuth"), "true");
  }
});

test("placeholder, non-Power BI, wrong-mode and invalid URLs stay unconfigured", () => {
  for (const url of [undefined, "https://unknown.test/reportEmbed?reportId=abc",
    "https://app.powerbi.com/view?r=abc", "https://app.powerbi.com/reportEmbed?reportId=REPLACE_REPORT_ID"]) {
    assert.deepEqual(pageLinks({ mode: "secure", url }), {});
  }
});

test("public mode keeps the service URL and does not append secure page parameters", () => {
  const url = "https://app.powerbi.com/view?r=example";
  assert.deepEqual(pageLinks({ mode: "public", url }), { overview: url });
  assert.equal(pageLinks({ mode: "public", url,
    pageUrls: { prices: "https://app.powerbi.com/view?r=another" } }).prices,
  "https://app.powerbi.com/view?r=another");
});

test("SDK adapter forwards navigation and detaches from its container", async () => {
  const handlers = new Map(), calls = [];
  const report = { on: (key, handler) => handlers.set(key, handler), off: key => handlers.delete(key),
    getPages: async () => [{ name: "page-a", displayName: "Overview", visibility: 0 }],
    setPage: page => calls.push(page), fullscreen: () => calls.push("fullscreen"), setAccessToken: () => {} };
  const container = {};
  const sdk = mountSdkReport({ embed: () => report, reset: value => assert.equal(value, container) },
    container, {}, { onPages: value => calls.push(value[0].name) });
  await handlers.get("loaded")();
  await sdk.navigate("page-b");
  sdk.fullscreen();
  sdk.dispose();
  assert.deepEqual(calls, ["page-a", "page-b", "fullscreen"]);
  assert.equal(handlers.size, 0);
});
