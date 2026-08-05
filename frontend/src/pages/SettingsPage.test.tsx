import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { type SettingsResponse } from "../api";
import { SettingsPage } from "./SettingsPage";

const SETTINGS: SettingsResponse = {
  wos_api_key: null,
  openalex_api_key: null,
  crossref_email: null,
  personalization_enabled: true,
  automatic_search_daily_limit: 10,
  onboarding_complete: true,
  avatar_url: null,
  display_name: "研究者",
  storage: "C:/data",
  cache_limit_mb: 500,
};

function parseJsonBody(init?: RequestInit): Record<string, unknown> {
  if (typeof init?.body !== "string") throw new Error("Expected a JSON request body");
  return JSON.parse(init.body) as Record<string, unknown>;
}

describe("SettingsPage", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("saves a custom display name and returns it to the app shell", async () => {
    const changed = vi.fn();
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url === "/api/settings" && init?.method === "PUT") {
        const body = parseJsonBody(init);
        return Promise.resolve(new Response(JSON.stringify({ ...SETTINGS, display_name: body.display_name }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }));
      }
      const payload = url === "/api/translation/model"
        ? { state: "missing", running: false }
        : [];
      return Promise.resolve(new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<SettingsPage settings={SETTINGS} onChange={changed} />);

    fireEvent.change(screen.getByLabelText("显示名称"), { target: { value: "Zyyyy" } });
    fireEvent.click(screen.getByRole("button", { name: "保存设置" }));

    await waitFor(() => expect(changed).toHaveBeenCalledWith(expect.objectContaining({
      display_name: "Zyyyy",
    })));
    const settingsCall = fetchMock.mock.calls.find(([url, init]) => (
      url === "/api/settings" && init?.method === "PUT"
    ));
    expect(settingsCall).toBeDefined();
    expect(parseJsonBody(settingsCall?.[1])).toEqual(expect.objectContaining({
      display_name: "Zyyyy",
    }));
  });
});
