import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PdfUpload } from "./PdfUpload";

describe("PdfUpload", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string"
        ? input
        : input instanceof URL ? input.href : input.url;
      let body: object;
      if (url.startsWith("/api/pdfs/preview")) {
        body = {
          token: "a".repeat(32), original_name: "paper.pdf", sha256: "b".repeat(64),
          size_bytes: 1024, page_count: 2,
          preview: {
            duplicate_level: "none", matches: [],
            candidates: [{
              field_name: "title", value: "Extracted title", page_number: 1,
              evidence: "Extracted title", method: "text", confidence: 0.8,
            }],
          },
        };
      } else if (url === "/api/pdfs/confirm") {
        body = { paper_id: 3, file_id: 8, job_id: 12, deduplicated: false };
      } else if (url === "/api/jobs/12") {
        body = {
          id: 12, kind: "pdf_processing", status: "completed",
          progress_current: 2, progress_total: 2, result: { pages: 2 },
          error_code: null, error_message: null,
        };
      } else {
        body = { updated: true };
      }
      return Promise.resolve(new Response(JSON.stringify(body), {
        status: 200, headers: { "Content-Type": "application/json" },
      }));
    }));
  });

  it("requires metadata review before permanently storing a valid PDF", async () => {
    const completed = vi.fn();
    const { container } = render(<PdfUpload paperId={3} onComplete={completed} />);
    const input = container.querySelector("input[type=file]");
    expect(input).not.toBeNull();
    const file = new File(["%PDF-1.4 test"], "paper.pdf", { type: "application/pdf" });
    fireEvent.change(input as HTMLInputElement, { target: { files: [file] } });
    expect(await screen.findByRole("dialog", { name: "核对 PDF 入库" })).toBeInTheDocument();
    expect(screen.getByDisplayValue("Extracted title")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认入库" }));
    expect(await screen.findByText("PDF 已永久保存并完成识别")).toBeInTheDocument();
    expect(completed).toHaveBeenCalledWith(3, 8);
  });
});
