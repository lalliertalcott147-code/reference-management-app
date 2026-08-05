import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LibraryPage } from "./LibraryPage";

describe("LibraryPage", () => {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url.startsWith("/api/libraries")) {
      return Promise.resolve(new Response(JSON.stringify([{
        id: 1, name: "我的文献", sort_order: 0, deleted_at: null, paper_count: 1,
      }]), { status: 200, headers: { "Content-Type": "application/json" } }));
    }
    if (url.startsWith("/api/library/papers")) {
      return Promise.resolve(new Response(JSON.stringify([{
        id: 7,
        title: "Copper catalyst",
        journal: "Catalysis Journal",
        year: 2026,
        doi: "10.1000/test",
        liked: false,
        saved: true,
        reading_status: "unread",
        has_pdf: false,
        note_id: null,
        note: "",
      }]), { status: 200, headers: { "Content-Type": "application/json" } }));
    }
    if (url === "/api/notes") {
      return Promise.resolve(new Response(JSON.stringify({ note_id: 9, version: 1 }), {
        status: 200, headers: { "Content-Type": "application/json" },
      }));
    }
    return Promise.resolve(new Response("{}", { status: 200 }));
  });

  beforeEach(() => vi.stubGlobal("fetch", fetchMock));
  afterEach(() => { vi.unstubAllGlobals(); fetchMock.mockClear(); });

  it("loads local papers and autosaves a note after editing", async () => {
    render(<LibraryPage />);
    expect(await screen.findByRole("heading", { name: "Copper catalyst" })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Copper catalyst笔记" }), {
      target: { value: "local insight" },
    });
    expect(screen.getByText("等待保存…")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("已保存 · v1")).toBeInTheDocument(), { timeout: 2000 });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/notes",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
