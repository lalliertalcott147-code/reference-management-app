import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { MergedPaper } from "../api";
import { PaperDetail } from "./PaperDetail";

const paper: MergedPaper = {
  identity: "doi:10.1000/test",
  doi: "10.1000/test",
  wos_uid: "WOS:1",
  title: "Catalyst design",
  authors: ["Ming Li"],
  journal: "Catalysis Journal",
  year: 2026,
  abstract: "An English abstract.",
  url: null,
  citations: 3,
  weak_match: false,
  provenance: {},
  sources: [{
    source: "wos",
    source_id: "WOS:1",
    title: "Catalyst design",
    doi: "10.1000/test",
    wos_uid: "WOS:1",
    authors: ["Ming Li"],
    journal: "Catalysis Journal",
    year: 2026,
    abstract: "An English abstract.",
    url: null,
    citations: 3,
  }],
};

describe("PaperDetail local translation", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string"
        ? input
        : input instanceof URL ? input.href : input.url;
      let body: object;
      if (url.endsWith("/api/translation/model")) {
        body = {
          state: "ready", repository: "tencent/Hy-MT2-1.8B-GGUF",
          filename: "model.gguf", size_bytes: 1, sha256: "hash",
          license: "Apache-2.0", running: false,
        };
      } else if (url.endsWith("/api/translation/jobs")) {
        body = { job_id: 7 };
      } else {
        body = {
          id: 7, kind: "translation", status: "completed",
          progress_current: 1, progress_total: 1,
          result: { translated_text: "催化剂设计", saved: true },
          error_code: null, error_message: null,
        };
      }
      return Promise.resolve(new Response(JSON.stringify(body), {
        status: 200, headers: { "Content-Type": "application/json" },
      }));
    }));
  });

  it("keeps the original visible and displays a saved local translation", async () => {
    const ensureSaved = vi.fn(() => Promise.resolve(19));
    render(<PaperDetail paper={paper} onClose={vi.fn()} ensureSaved={ensureSaved} />);
    expect(screen.getByText("Catalyst design")).toBeInTheDocument();
    const buttons = await screen.findAllByRole("button", { name: "在本机翻译并保存" });
    fireEvent.click(buttons[0]);
    expect(await screen.findByText("催化剂设计")).toBeInTheDocument();
    expect(screen.getByText("Catalyst design")).toBeInTheDocument();
    expect(ensureSaved).toHaveBeenCalledOnce();
  });
});
