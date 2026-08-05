import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ImportPage } from "./ImportPage";

describe("ImportPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({
      format: "ris",
      total: 2,
      new: 1,
      duplicates: 1,
      missing_doi: 0,
      conflicts: 1,
      issues: [],
    }), { status: 200, headers: { "Content-Type": "application/json" } }))));
  });

  it("shows a no-write preview before confirmation", async () => {
    const { container } = render(<ImportPage />);
    const input = container.querySelector("input[type=file]");
    expect(input).not.toBeNull();
    const file = new File(["TY  - JOUR"], "records.ris", { type: "text/plain" });
    fireEvent.change(input as HTMLInputElement, { target: { files: [file] } });
    expect(await screen.findByRole("heading", { name: "导入预览" })).toBeInTheDocument();
    expect(screen.getByText("确认导入")).toBeInTheDocument();
  });
});
