import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProfileAvatar } from "./ProfileAvatar";

describe("ProfileAvatar", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("uploads a supported image and renders the persisted avatar", async () => {
    const uploaded = vi.fn();
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      void init;
      return Promise.resolve(new Response(JSON.stringify({
        avatar_url: "/api/profile/avatar?v=abc",
      }), { status: 200, headers: { "Content-Type": "application/json" } }));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { rerender } = render(<ProfileAvatar avatarUrl={null} onUploaded={uploaded} />);
    const file = new File([new Uint8Array([1, 2, 3])], "avatar.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("上传个人头像"), { target: { files: [file] } });

    expect(await screen.findByText("头像已保存")).toBeInTheDocument();
    expect(uploaded).toHaveBeenCalledWith("/api/profile/avatar?v=abc");
    expect(fetchMock).toHaveBeenCalledWith("/api/profile/avatar", expect.objectContaining({
      method: "POST",
    }));
    expect(fetchMock.mock.calls[0]?.[1]?.body).toBeInstanceOf(FormData);

    rerender(<ProfileAvatar avatarUrl="/api/profile/avatar?v=abc" onUploaded={uploaded} />);
    expect(screen.getByRole("img", { name: "个人头像" })).toHaveAttribute(
      "src",
      "/api/profile/avatar?v=abc",
    );
  });

  it("rejects oversized images before sending them", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<ProfileAvatar avatarUrl={null} onUploaded={vi.fn()} />);
    const file = new File([new Uint8Array(5 * 1024 * 1024 + 1)], "large.png", {
      type: "image/png",
    });

    fireEvent.change(screen.getByLabelText("上传个人头像"), { target: { files: [file] } });

    expect(await screen.findByText(/不超过 5 MB/)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
