import React, { useEffect, useRef, useState } from "react";
import { pageLinks, pages } from "./config.mjs";
import "./analytics.css";

const h = React.createElement;

function ReportFrame({ url, label }) {
  const [status, setStatus] = useState("loading");
  const [notice, setNotice] = useState("");
  const [attempt, setAttempt] = useState(0);
  const frame = useRef(null);
  useEffect(() => {
    if (status !== "loading") return;
    const timer = setTimeout(() => setStatus("slow"), 15000);
    return () => clearTimeout(timer);
  }, [attempt, status]);

  async function fullscreen() {
    setNotice("");
    try {
      if (!frame.current?.requestFullscreen) throw new Error("Unavailable");
      await frame.current.requestFullscreen();
    } catch {
      setNotice("Fullscreen is unavailable. Open the report in a new tab.");
    }
  }

  return h("div", null,
    h("div", { className: "im-actions" },
      h("button", { type: "button", onClick: fullscreen }, "Fullscreen"),
      h("button", { type: "button", onClick: () => { setStatus("loading"); setAttempt(n => n + 1); } }, "Reload report"),
      h("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, "Open in Power BI")),
    h("p", { role: "status", className: "im-status" },
      { loading: "Loading the Power BI frame…", slow: "Taking longer than expected. Reload or open the report directly.",
        error: "The frame could not load. Reload or open the report directly.", loaded: "" }[status] || notice),
    h("iframe", { key: attempt, ref: frame, className: "im-report", src: url, title: label,
      allow: "fullscreen", allowFullScreen: true, onLoad: () => setStatus("loaded"),
      onError: () => setStatus("error") }));
}

export function Analytics({ config }) {
  const [selection, setSelection] = useState("overview");
  const links = pageLinks(config);
  const configured = pages.filter(({ key }) => links[key]);
  const active = configured.find(({ key }) => key === selection) ?? configured[0];
  return h("section", { className: "im-analytics" },
    h("h1", null, "Marketplace analytics"),
    h("p", null, "Historical catalog records. Flipkart was crawled in 2015–2016. The Myntra observation date and currency are unspecified. Current prices and availability are unverified."),
    configured.length > 1 && h("nav", { "aria-label": "Analytics report pages" },
      ...configured.map(({ key, name }) => h("button",
        { key, type: "button", "aria-pressed": key === active?.key, onClick: () => setSelection(key) }, name))),
    active
      ? h(React.Fragment, null,
        configured.length < pages.length && h("p", null, "Use the page navigator inside the report to reach all four pages."),
        h(ReportFrame, { key: links[active.key], url: links[active.key], label: "IntelliMarket analytics — " + active.name }))
      : h("p", { role: "status" }, "Analytics is awaiting a configured Power BI embed link."));
}
