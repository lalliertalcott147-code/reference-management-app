import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { HomePage } from "./HomePage";

afterEach(() => vi.unstubAllGlobals());

it("shows transparent recommendation reasons and marks alerts read", async () => {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string"
      ? input
      : input instanceof URL
        ? input.href
        : input.url;
    if (url === "/api/recommendations") return Promise.resolve(new Response(JSON.stringify([{
      paper_id: 1,
      title: "Photocatalysis paper",
      journal: "Catalysis Today",
      year: 2026,
      score: 8,
      reasons: ["匹配研究主题“光催化”: photocatalysis"],
    }]), { status: 200, headers: { "Content-Type": "application/json" } }));
    if (url.startsWith("/api/alerts")) return Promise.resolve(new Response(JSON.stringify([{
      id: 2,
      kind: "saved_search",
      title: "有新结果",
      message: "发现 1 篇此前未见的文献。",
      related_type: "saved_search",
      related_id: 3,
      is_read: false,
      created_at: "2026-08-05T10:00:00Z",
    }]), { status: 200, headers: { "Content-Type": "application/json" } }));
    return Promise.resolve(new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } }));
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<HomePage health={{
    status: "ok", version: "0.1.0", mode: "local-single-user", database: "ready",
    storage: "C:/data", lifecycle: { active_tabs: 1, had_tab: true, empty_for_seconds: null, shutdown_due: false },
  }} />);
  expect(await screen.findByText("Photocatalysis paper")).toBeInTheDocument();
  expect(screen.getByText(/匹配研究主题/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "全部已读" }));
  expect(fetchMock).toHaveBeenCalledWith("/api/alerts/read", expect.objectContaining({ method: "POST" }));
});
