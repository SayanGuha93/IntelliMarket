import React from "react";
import { createRoot } from "react-dom/client";
import { Analytics } from "./Analytics.mjs";

const env = import.meta.env;
const config = {
  mode: env.VITE_PBI_MODE,
  url: env.VITE_PBI_EMBED_URL,
  pageNames: { overview: env.VITE_PBI_OVERVIEW, prices: env.VITE_PBI_PRICES,
    compare: env.VITE_PBI_COMPARE, ratings: env.VITE_PBI_RATINGS },
  pageUrls: { overview: env.VITE_PBI_OVERVIEW_URL, prices: env.VITE_PBI_PRICES_URL,
    compare: env.VITE_PBI_COMPARE_URL, ratings: env.VITE_PBI_RATINGS_URL },
};
createRoot(document.getElementById("root")).render(React.createElement(Analytics, { config }));
