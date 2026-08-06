import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LibraryWorkspace } from "./LibraryWorkspace";

describe("LibraryWorkspace", () => {
  let nextElementId = 20;
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
      const payload = JSON.parse(init.body) as { element_type?: string };
      if (!payload.element_type) throw new Error("Expected an element type");
      nextElementId += 1;
      return Promise.resolve(new Response(JSON.stringify({ id: nextElementId }), { status: 200 }));
    }
    if (url.startsWith("/api/library-workspace/elements/")) {
      return Promise.resolve(new Response(JSON.stringify(
        init?.method === "DELETE" ? { deleted: true } : { updated: true },
      ), { status: 200 }));
    }
    return Promise.resolve(new Response("{}", { status: 200 }));
  });

  beforeEach(() => { nextElementId = 20; vi.stubGlobal("fetch", fetchMock); });
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
    fireEvent.pointerDown(screen.getByRole("button", {
      name: "缩放文章卡片 Catalyst design",
    }), { pointerId: 6, clientX: 920, clientY: 384 });
    fireEvent.pointerMove(handle.closest(".workspace-canvas")!, { clientX: 1020, clientY: 464 });
    fireEvent.pointerUp(handle.closest(".workspace-canvas")!);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/library-workspace/cards/8",
      expect.objectContaining({ method: "PUT" }),
    ));
  });

  it("provides PPT insertion, transform, style, grouping, layering, clipboard, and history tools", async () => {
    render(<LibraryWorkspace libraryId={1} papers={[]} />);
    await screen.findByRole("heading", { name: "Catalyst design" });
    const canvas = document.querySelector(".workspace-canvas") as HTMLElement;

    fireEvent.click(screen.getByRole("button", { name: "添加文字" }));
    fireEvent.click(canvas, { clientX: 320, clientY: 440 });
    const text = await screen.findByRole("textbox", { name: "编辑文字 21" });
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

    const moveHandle = screen.getByRole("button", { name: "移动对象 21" });
    fireEvent.pointerDown(moveHandle, { pointerId: 2, clientX: 320, clientY: 440 });
    fireEvent.pointerMove(canvas, { clientX: 410, clientY: 500 });
    fireEvent.pointerUp(canvas);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/library-workspace/elements/21",
      expect.objectContaining({ method: "PUT" }),
    ));

    fireEvent.pointerDown(screen.getByRole("button", { name: "缩放对象 21" }), {
      pointerId: 3, clientX: 620, clientY: 600,
    });
    fireEvent.pointerMove(canvas, { clientX: 700, clientY: 650 });
    fireEvent.pointerUp(canvas);
    fireEvent.pointerDown(screen.getByRole("button", { name: "旋转对象 21" }), {
      pointerId: 4, clientX: 470, clientY: 400,
    });
    fireEvent.pointerMove(canvas, { clientX: 560, clientY: 470 });
    fireEvent.pointerUp(canvas);

    fireEvent.change(screen.getByRole("combobox", { name: "字体" }), { target: { value: "Arial" } });
    fireEvent.change(screen.getByRole("spinbutton", { name: "字号" }), { target: { value: "28" } });
    fireEvent.change(screen.getByRole("combobox", { name: "文字对齐" }), { target: { value: "center" } });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/library-workspace/elements/21",
      expect.objectContaining({ method: "PUT" }),
    ));

    fireEvent.click(screen.getByRole("button", { name: "添加矩形" }));
    fireEvent.click(canvas, { clientX: 720, clientY: 460 });
    expect(await screen.findByLabelText("画布对象 22")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "添加圆形" }));
    fireEvent.click(canvas, { clientX: 980, clientY: 460 });
    expect(await screen.findByLabelText("画布对象 23")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "添加直线" }));
    fireEvent.click(canvas, { clientX: 500, clientY: 600 });
    expect(await screen.findByLabelText("画布对象 24")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "添加箭头" }));
    fireEvent.click(canvas, { clientX: 800, clientY: 700 });
    expect(await screen.findByLabelText("画布对象 25")).toBeInTheDocument();

    fireEvent.pointerDown(screen.getByLabelText("画布对象 21"), {
      pointerId: 5, clientX: 410, clientY: 500, shiftKey: true,
    });
    fireEvent.pointerUp(canvas);
    fireEvent.click(screen.getByRole("button", { name: "组合" }));
    fireEvent.click(screen.getByRole("button", { name: "置于顶层" }));
    fireEvent.change(screen.getByRole("combobox", { name: "对齐与分布" }), {
      target: { value: "left" },
    });

    fireEvent.click(screen.getByRole("button", { name: "复制" }));
    fireEvent.click(screen.getByRole("button", { name: "粘贴" }));
    await waitFor(() => expect(screen.getByLabelText("画布对象 26")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "删除选中" }));
    fireEvent.click(screen.getByRole("button", { name: "撤销" }));
    await waitFor(() => expect(screen.getByLabelText("画布对象 26")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "重做" }));
    await waitFor(() => expect(screen.queryByLabelText("画布对象 26")).not.toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "放大画布" }));
    expect(screen.getByText("110%")).toBeInTheDocument();
  });

  it("inserts persistent images and grows the canvas while scrolling", async () => {
    render(<LibraryWorkspace libraryId={1} papers={[]} />);
    await screen.findByRole("heading", { name: "Catalyst design" });
    const file = new File([new Uint8Array([137, 80, 78, 71])], "figure.png", {
      type: "image/png",
    });
    fireEvent.change(screen.getByLabelText("选择画布图片"), { target: { files: [file] } });
    expect(await screen.findByAltText("画布图片")).toBeInTheDocument();
    const createCall = fetchMock.mock.calls.find(([input, init]) => (
      input === "/api/libraries/1/workspace/elements" && init?.method === "POST"
    ));
    expect(createCall?.[1]?.body).toContain("data:image/png;base64,");

    const scroll = document.querySelector(".workspace-scroll") as HTMLElement;
    Object.defineProperties(scroll, {
      scrollTop: { configurable: true, value: 900 },
      clientHeight: { configurable: true, value: 700 },
      scrollHeight: { configurable: true, value: 1700 },
    });
    fireEvent.scroll(scroll);
    await waitFor(() => expect(document.querySelector(".workspace-canvas")).toHaveStyle({
      minHeight: "2100px",
    }));
  });
});
