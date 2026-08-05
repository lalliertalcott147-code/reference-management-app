import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { JournalsPage } from "./JournalsPage";

afterEach(() => vi.unstubAllGlobals());

it("follows a journal and manually checks saved searches", async () => {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string"
      ? input
      : input instanceof URL
        ? input.href
        : input.url;
    if (url === "/api/journals/subscriptions" && !init?.method) {
      return Promise.resolve(new Response(JSON.stringify([{
        id: 1, title: "Catalysis Today", issn_l: null, enabled: true,
        next_run_at: null, last_success_at: "2026-08-05T10:00:00Z",
        last_error: null, last_match_count: 2,
      }]), { status: 200, headers: { "Content-Type": "application/json" } }));
    }
    if (url === "/api/saved-searches" && !init?.method) {
      return Promise.resolve(new Response(JSON.stringify([{
        id: 4, name: "每日电催化", query: { text: "electrocatalysis", field: "topic" },
        enabled: true, next_run_at: null, last_success_at: null,
        last_error: null, last_new_count: 0,
      }]), { status: 200, headers: { "Content-Type": "application/json" } }));
    }
    if (url.endsWith("/run")) return Promise.resolve(new Response(JSON.stringify({ new_count: 1 }), { status: 200, headers: { "Content-Type": "application/json" } }));
    return Promise.resolve(new Response(JSON.stringify({ id: 7 }), { status: 200, headers: { "Content-Type": "application/json" } }));
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<JournalsPage />);
  expect(await screen.findByText("Catalysis Today")).toBeInTheDocument();
  fireEvent.click(screen.getAllByRole("button", { name: "立即运行" })[0]);
  expect(await screen.findByText(/发现 1 篇此前未见/)).toBeInTheDocument();
  fireEvent.change(screen.getByPlaceholderText("例如 Catalysis Today"), { target: { value: "ACS Catalysis" } });
  fireEvent.click(screen.getByRole("button", { name: "关注" }));
  expect(fetchMock).toHaveBeenCalledWith("/api/journals/subscriptions", expect.objectContaining({ method: "POST" }));
});
