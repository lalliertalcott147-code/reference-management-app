import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LibraryWorkspace } from "./LibraryWorkspace";

describe("LibraryWorkspace", () => {
  const workspace = {
    library_id: 1,
    body: "研究总览",
    note_x: 24,
    note_y: 24,
    note_width: 520,
    note_height: 260,
    version: 1,
    updated_at: "2026-08-06T00:00:00Z",
    cards: [{
      id: 8,
      paper_id: 7,
      x: 580,
      y: 24,
      width: 340,
      height: 360,
      title: "Catalyst design",
      title_translation: "催化剂设计",
      abstract: "Original abstract",
      abstract_translation: "中文摘要",
      file_id: 12,
      notes: [{ id: 3, body: "文章笔记", updated_at: "2026-08-06T00:00:00Z" }],
    }],
  };
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url === "/api/libraries/1/workspace" && init?.method === "PUT") {
      return Promise.resolve(new Response(JSON.stringify({ version: 2 }), { status: 200 }));
    }
    if (url === "/api/libraries/1/workspace") {
      return Promise.resolve(new Response(JSON.stringify(workspace), { status: 200 }));
    }
    if (url === "/api/library-workspace/cards/8") {
      return Promise.resolve(new Response(JSON.stringify({ updated: true }), { status: 200 }));
    }
    return Promise.resolve(new Response("{}", { status: 200 }));
  });

  beforeEach(() => vi.stubGlobal("fetch", fetchMock));
  afterEach(() => { vi.unstubAllGlobals(); fetchMock.mockClear(); });

  it("shows article context, autosaves the global note, and persists card dragging", async () => {
    render(<LibraryWorkspace libraryId={1} papers={[]} />);
    expect(await screen.findByRole("heading", { name: "Catalyst design" })).toBeInTheDocument();
    expect(screen.getByText("催化剂设计")).toBeInTheDocument();
    expect(screen.getByText("Original abstract")).toBeInTheDocument();
    expect(screen.getByText("中文摘要")).toBeInTheDocument();
    expect(screen.getByText("文章笔记")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "阅读并翻译 PDF" })).toHaveAttribute(
      "href", "#reader?paper=7&file=12",
    );

    fireEvent.change(screen.getByRole("textbox", { name: "总笔记" }), {
      target: { value: "更新后的研究总览" },
    });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/libraries/1/workspace",
      expect.objectContaining({ method: "PUT" }),
    ), { timeout: 2000 });

    const handle = screen.getByText("文章卡片 · 拖动排布");
    fireEvent.pointerDown(handle, { pointerId: 1, clientX: 600, clientY: 40 });
    fireEvent.pointerMove(handle.closest(".workspace-canvas")!, { clientX: 680, clientY: 100 });
    fireEvent.pointerUp(handle.closest(".workspace-canvas")!);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/library-workspace/cards/8",
      expect.objectContaining({ method: "PUT" }),
    ));
  });
});
