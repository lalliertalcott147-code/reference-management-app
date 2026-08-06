import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LibraryPage } from "./LibraryPage";

describe("LibraryPage", () => {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url === "/api/libraries/1/papers" && init?.method === "POST") {
      return Promise.resolve(new Response(JSON.stringify({ added: true }), {
        status: 200, headers: { "Content-Type": "application/json" },
      }));
    }
    if (url === "/api/library/workspace") {
      return Promise.resolve(new Response(JSON.stringify({
        library_id: null,
        body: "全部文献的独立总笔记",
        note_x: 24,
        note_y: 24,
        note_width: 520,
        note_height: 260,
        version: 1,
        updated_at: "2026-08-06T00:00:00Z",
        cards: [],
        elements: [],
      }), { status: 200, headers: { "Content-Type": "application/json" } }));
    }
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
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); fetchMock.mockClear(); });

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

  it("adds an uploaded PDF paper from all papers to a custom library", async () => {
    render(<LibraryPage />);
    expect(await screen.findByRole("heading", { name: "Copper catalyst" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "全部文献" }));
    fireEvent.change(screen.getByRole("combobox", {
      name: "将 Copper catalyst 添加到知识库",
    }), { target: { value: "1" } });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/libraries/1/papers",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ paper_id: 7 }),
      }),
    ));
    expect(await screen.findByText("已将“Copper catalyst”添加到“我的文献”")).toBeInTheDocument();
  });

  it("offers an independent global note in all papers", async () => {
    render(<LibraryPage />);
    expect(await screen.findByRole("heading", { name: "Copper catalyst" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "全部文献" }));
    fireEvent.click(screen.getByRole("button", { name: "总笔记" }));
    expect(await screen.findByRole("textbox", { name: "总笔记" })).toHaveValue(
      "全部文献的独立总笔记",
    );
    expect(fetchMock).toHaveBeenCalledWith("/api/library/workspace", {
      credentials: "same-origin",
    });
  });
});
