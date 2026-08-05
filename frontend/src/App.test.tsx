import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";


describe("App", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
      if (url === "/api/health") {
        return Promise.resolve(new Response(JSON.stringify({
          status: "ok",
          version: "0.1.0",
          mode: "local-single-user",
          database: "ready",
          storage: "C:/data",
          lifecycle: {
            active_tabs: 1,
            had_tab: true,
            empty_for_seconds: null,
            shutdown_due: false,
          },
        }), { status: 200, headers: { "Content-Type": "application/json" } }));
      }
      if (url === "/api/settings") {
        return Promise.resolve(new Response(JSON.stringify({
          wos_api_key: null,
          openalex_api_key: null,
          crossref_email: null,
          personalization_enabled: true,
          automatic_search_daily_limit: 10,
          onboarding_complete: true,
          avatar_url: null,
          storage: "C:/data",
          cache_limit_mb: 500,
        }), { status: 200, headers: { "Content-Type": "application/json" } }));
      }
      if (url.startsWith("/api/recommendations") || url.startsWith("/api/alerts")) {
        return Promise.resolve(new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } }));
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    }));
    Object.defineProperty(navigator, "sendBeacon", { value: vi.fn(), configurable: true });
    sessionStorage.clear();
    location.hash = "#home";
  });

  afterEach(() => vi.unstubAllGlobals());

  it("renders navigation and connected backend state", async () => {
    render(<App />);
    expect(await screen.findByRole("navigation", { name: "主导航" })).toBeInTheDocument();
    expect(await screen.findByText(/本地服务已连接/)).toHaveTextContent("版本 0.1.0");
  });
});
