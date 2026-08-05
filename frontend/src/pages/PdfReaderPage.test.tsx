import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  page: {
    getViewport: ({ scale }: { scale: number }) => ({ width: 612 * scale, height: 792 * scale }),
    render: () => ({ promise: Promise.resolve(), cancel: vi.fn() }),
    streamTextContent: () => new ReadableStream(),
  },
}));

vi.mock("pdfjs-dist/build/pdf.worker.min.mjs?url", () => ({ default: "worker.mjs" }));
vi.mock("pdfjs-dist", () => ({
  GlobalWorkerOptions: { workerSrc: "" },
  TextLayer: class {
    render() { return Promise.resolve(); }
    cancel() { /* test implementation */ }
  },
  getDocument: () => ({
    promise: Promise.resolve({
      numPages: 2,
      getPage: () => Promise.resolve(mocks.page),
      getOutline: () => Promise.resolve([]),
      getDestination: () => Promise.resolve(null),
      getPageIndex: () => Promise.resolve(0),
    }),
    destroy: () => Promise.resolve(),
  }),
}));

import { PdfReaderPage } from "./PdfReaderPage";

describe("PdfReaderPage", () => {
  beforeEach(() => {
    location.hash = "#reader?paper=3&file=8";
    vi.stubGlobal("IntersectionObserver", class {
      observe() { /* viewport rendering is covered by browser integration */ }
      disconnect() { /* viewport rendering is covered by browser integration */ }
    });
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string"
        ? input
        : input instanceof URL ? input.href : input.url;
      let body: object;
      if (url.endsWith("/pages")) {
        body = [
          { page_number: 1, width: 612, height: 792, classification: "text", source: "text", content: "catalyst alpha", blocks: [], confidence: 1 },
          { page_number: 2, width: 612, height: 792, classification: "text", source: "text", content: "kinetics beta", blocks: [], confidence: 1 },
        ];
      } else if (url.includes("/position") && !url.endsWith("/position")) {
        body = { page_number: 2, scale: 1.25, scroll_offset: 60 };
      } else if (url.includes("/annotations")) {
        body = [{
          id: 2, note_id: 9, annotation_type: "highlight", page_number: 2,
          color: "#F4D35E", selected_text: "kinetics", prefix_text: "",
          suffix_text: "", rects: [{ x: .1, y: .2, width: .3, height: .04 }],
          comment_text: "saved note", is_stale: false, updated_at: "now",
        }];
      } else {
        body = { updated: true };
      }
      return Promise.resolve(new Response(JSON.stringify(body), {
        status: 200, headers: { "Content-Type": "application/json" },
      }));
    }));
  });

  it("restores reading state and searches extracted page text", async () => {
    render(<PdfReaderPage />);
    expect(await screen.findByText("/ 2")).toBeInTheDocument();
    expect(screen.getByDisplayValue("2")).toBeInTheDocument();
    expect(screen.getByText("saved note")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("搜索 PDF 文本"), {
      target: { value: "kinetics" },
    });
    expect(screen.getByRole("button", { name: "第 2 页匹配" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "高亮" })).toBeDisabled();
  });
});
