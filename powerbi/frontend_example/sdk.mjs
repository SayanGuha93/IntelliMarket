/**
 * Optional adapter for an existing powerbi-client Service. The host supplies
 * a short-lived Entra or embed token and the matching models.TokenType value.
 */
export function mountSdkReport(service, container, { reportId, embedUrl, accessToken, tokenType }, callbacks = {}) {
  const report = service.embed(container, { type: "report", id: reportId, embedUrl, accessToken, tokenType });
  let disposed = false;
  const error = () => { if (!disposed) callbacks.onError?.("Power BI could not complete the request."); };
  const loaded = async () => {
    try {
      const pages = await report.getPages();
      if (!disposed) callbacks.onPages?.(pages.filter(page => page.visibility !== 1)
        .map(({ name, displayName }) => ({ name, displayName })));
    } catch { error(); }
  };
  report.on("loaded", loaded);
  report.on("rendered", () => { if (!disposed) callbacks.onRendered?.(); });
  report.on("pageChanged", ({ detail }) => { if (!disposed) callbacks.onPageChanged?.(detail.newPage.name); });
  report.on("error", error);
  return {
    navigate: (name) => report.setPage(name),
    fullscreen: () => report.fullscreen(),
    refreshToken: (token) => report.setAccessToken(token),
    dispose() {
      disposed = true;
      for (const event of ["loaded", "rendered", "pageChanged", "error"]) report.off(event);
      service.reset(container);
    },
  };
}
