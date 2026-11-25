export const pages = [
  { key: "overview", name: "Marketplace Overview" },
  { key: "prices", name: "Price and Discount Analytics" },
  { key: "compare", name: "Flipkart vs Myntra" },
  { key: "ratings", name: "Product and Rating Analytics" },
];

function appUrl(value, path) {
  try {
    const url = new URL(value);
    if (url.origin === "https://app.powerbi.com" && url.pathname === path &&
        !url.username && !url.password) return url;
  } catch {
    // Placeholder or malformed value.
  }
  return null;
}

export function pageLinks(config) {
  const secure = config.mode === "secure";
  if (!secure && config.mode !== "public") return {};
  const path = secure ? "/reportEmbed" : "/view";
  const base = appUrl(config.url, path);
  const valid = (url) => url && url.searchParams.get(secure ? "reportId" : "r") &&
    !/^(REPLACE|PLACEHOLDER)/i.test(url.searchParams.get(secure ? "reportId" : "r"));
  const links = {};
  for (const { key } of pages) {
    if (secure && valid(base) && config.pageNames?.[key] && !config.pageNames[key].startsWith("REPLACE")) {
      const url = new URL(base);
      url.searchParams.set("pageName", config.pageNames[key]);
      links[key] = url.href;
    } else if (!secure) {
      const url = appUrl(config.pageUrls?.[key], path);
      if (valid(url)) links[key] = url.href;
    }
  }
  if (valid(base)) {
    const url = new URL(base);
    links.overview ??= url.href;
  }
  return links;
}
