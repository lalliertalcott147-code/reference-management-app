import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PdfSelectionTranslator } from "./PdfSelectionTranslator";

describe("PdfSelectionTranslator", () => {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url === "/api/translation/text-jobs") {
      return Promise.resolve(new Response(JSON.stringify({ job_id: 19 }), { status: 200 }));
    }
    if (url === "/api/jobs/19") {
      return Promise.resolve(new Response(JSON.stringify({
        id: 19,
        kind: "selection_translation",
        status: "completed",
        progress_current: 1,
        progress_total: 1,
        result: { field_name: "selection", translated_text: "中文译文" },
        error_code: null,
        error_message: null,
      }), { status: 200 }));
    }
    if (url === "/api/notes/append") {
      if (typeof init?.body !== "string") throw new Error("Expected a JSON request body");
      const body = JSON.parse(init.body) as { body: string };
      expect(body.body).toContain("[PDF 第 4 页 · 文件 12]");
      expect(body.body).toContain("原文：selected text");
      expect(body.body).toContain("译文：中文译文");
      return Promise.resolve(new Response(JSON.stringify({ note_id: 2, version: 3 }), { status: 200 }));
    }
    return Promise.resolve(new Response("{}", { status: 404 }));
  });

  beforeEach(() => vi.stubGlobal("fetch", fetchMock));
  afterEach(() => { vi.unstubAllGlobals(); fetchMock.mockClear(); });

  it("translates selected PDF text and appends the source and translation to notes", async () => {
    render(<PdfSelectionTranslator paperId={7} fileId={12} selection={{ page: 4, text: "selected text" }} />);
    fireEvent.click(screen.getByRole("button", { name: "翻译选中文本" }));
    expect(await screen.findByText("中文译文")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "添加到文章笔记" }));
    await waitFor(() => expect(screen.getByText("原文和译文已添加到文章笔记")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/notes/append",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
