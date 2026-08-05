import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    elements: [],
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
    if (url === "/api/libraries/1/workspace/elements" && init?.method === "POST") {
      if (typeof init.body !== "string") throw new Error("Expected a JSON request body");
      const body = JSON.parse(init.body) as { element_type: "text" | "line" };
      return Promise.resolve(new Response(JSON.stringify({
        id: body.element_type === "text" ? 21 : 22,
      }), { status: 200 }));
    }
    if (url.startsWith("/api/library-workspace/elements/")) {
      return Promise.resolve(new Response(JSON.stringify(
        init?.method === "DELETE" ? { deleted: true } : { updated: true },
      ), { status: 200 }));
    }
    return Promise.resolve(new Response("{}", { status: 200 }));
  });

  beforeEach(() => vi.stubGlobal("fetch", fetchMock));
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); fetchMock.mockClear(); });

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

  it("adds, edits, moves, and deletes text and line elements from the side toolbar", async () => {
    render(<LibraryWorkspace libraryId={1} papers={[]} />);
    await screen.findByRole("heading", { name: "Catalyst design" });
    const canvas = document.querySelector(".workspace-canvas") as HTMLElement;

    fireEvent.click(screen.getByRole("button", { name: "添加文字" }));
    fireEvent.click(canvas, { clientX: 320, clientY: 440 });
    const text = await screen.findByRole("textbox", { name: "文字元素 21" });
    fireEvent.change(text, { target: { value: "可自由移动的研究结论" } });
    fireEvent.blur(text);
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([input, init]) => (
        input === "/api/library-workspace/elements/21" && init?.method === "PUT"
      ));
      expect(call).toBeDefined();
      const body = call?.[1]?.body;
      expect(typeof body).toBe("string");
      expect(body).toContain("可自由移动的研究结论");
    });

    const textHandle = screen.getByText("文字 · 拖动");
    fireEvent.pointerDown(textHandle, { pointerId: 2, clientX: 320, clientY: 440 });
    fireEvent.pointerMove(canvas, { clientX: 410, clientY: 500 });
    fireEvent.pointerUp(canvas);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/library-workspace/elements/21",
      expect.objectContaining({ method: "PUT" }),
    ));

    fireEvent.click(screen.getByRole("button", { name: "添加直线" }));
    fireEvent.click(canvas, { clientX: 500, clientY: 600 });
    const line = await screen.findByRole("button", { name: "直线元素 22" });
    fireEvent.pointerDown(line, { pointerId: 3, clientX: 500, clientY: 600 });
    fireEvent.pointerMove(canvas, { clientX: 560, clientY: 640 });
    fireEvent.pointerUp(canvas);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/library-workspace/elements/22",
      expect.objectContaining({ method: "PUT" }),
    ));
    fireEvent.click(line);
    fireEvent.click(screen.getByRole("button", { name: "删除选中" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/library-workspace/elements/22",
      { method: "DELETE", credentials: "same-origin" },
    ));
  });
});
