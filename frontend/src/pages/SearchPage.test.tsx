import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SearchPage } from "./SearchPage";

describe("SearchPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({
      papers: [{
        identity: "doi:10.1000/test",
        doi: "10.1000/test",
        wos_uid: "WOS:1",
        title: "A catalyst paper",
        authors: ["Ming Li"],
        journal: "Catalysis Journal",
        year: 2026,
        abstract: "Copper catalyst abstract",
        url: null,
        citations: 4,
        weak_match: false,
        provenance: {},
        sources: [{
          source: "wos",
          source_id: "WOS:1",
          title: "A catalyst paper",
          doi: "10.1000/test",
          wos_uid: "WOS:1",
          authors: ["Ming Li"],
          journal: "Catalysis Journal",
          year: 2026,
          abstract: null,
          url: null,
          citations: 4,
        }],
      }],
      statuses: [{ source: "wos", state: "success", message: "ok", fetched_at: null }],
      recognized_queries: ["光催化", "photocatalysis"],
    }), { status: 200, headers: { "Content-Type": "application/json" } }))));
  });

  it("submits an explicit query and opens the accessible detail drawer", async () => {
    render(<SearchPage />);
    fireEvent.change(screen.getByPlaceholderText(/输入关键词/), { target: { value: "光催化 / photocatalysis" } });
    fireEvent.click(screen.getByRole("button", { name: "检索" }));
    expect(await screen.findByRole("button", { name: "A catalyst paper" })).toBeInTheDocument();
    expect(screen.getByText("WoS · success")).toBeInTheDocument();
    expect(screen.getByText("已同时识别：光催化 · photocatalysis")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "查看详情" }));
    expect(screen.getByRole("dialog", { name: "A catalyst paper" })).toBeInTheDocument();
  });
});
