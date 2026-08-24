import React from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const mockUseSession = vi.fn();
vi.mock("next-auth/react", () => ({
  useSession: () => mockUseSession(),
}));

vi.mock("@/lib/api", () => ({
  api: { get: vi.fn() },
}));

import { api } from "@/lib/api";
import { PublishingPausedBanner } from "@/components/layout/PublishingPausedBanner";

describe("PublishingPausedBanner", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    mockUseSession.mockReturnValue({ data: { user: { role: "editor" } } });
  });

  it("shows the banner when publishing is paused", async () => {
    vi.mocked(api.get).mockResolvedValue({ enabled: false });

    render(<PublishingPausedBanner />);

    expect(
      await screen.findByText(/Publishing is paused/)
    ).toBeInTheDocument();
    // Editors see the state but not the admin manage link.
    expect(screen.queryByRole("link", { name: "Manage" })).toBeNull();
  });

  it("links admins to the publishing controls", async () => {
    mockUseSession.mockReturnValue({ data: { user: { role: "admin" } } });
    vi.mocked(api.get).mockResolvedValue({ enabled: false });

    render(<PublishingPausedBanner />);

    const link = await screen.findByRole("link", { name: "Manage" });
    expect(link).toHaveAttribute("href", "/system#publishing");
  });

  it("renders nothing while publishing is enabled", async () => {
    vi.mocked(api.get).mockResolvedValue({ enabled: true });

    const { container } = render(<PublishingPausedBanner />);

    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the status fetch fails (best-effort)", async () => {
    vi.mocked(api.get).mockRejectedValue(new Error("boom"));

    const { container } = render(<PublishingPausedBanner />);

    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
