import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ChannelsTab, type ChannelsTabProps } from "@/components/brand/tabs/ChannelsTab";
import { ALL_CHANNELS, CHANNEL_DISPLAY_NAMES } from "@/types";

// ChannelsTab imports the api client (used by the LinkedIn token-status
// widget); stub it so the test never pulls in next-auth or hits the network.
vi.mock("@/lib/api", () => ({
  api: { get: vi.fn().mockResolvedValue({}) },
}));

function makeProps(overrides?: Partial<ChannelsTabProps>): ChannelsTabProps {
  return {
    brandId: "b-1",
    channelConfigs: {
      // enabled but missing credentials → needs setup
      instagram: {
        enabled: true,
        configured: false,
        handle: "@naturespan",
        access_token: "stored-token",
      },
      // enabled and fully configured
      facebook: { enabled: true, configured: true },
      teams: { enabled: false, configured: false },
    },
    expandedChannel: null,
    savingChannels: false,
    allChannels: ALL_CHANNELS,
    channelIconStyled: {},
    channelDisplayNames: CHANNEL_DISPLAY_NAMES,
    onToggleChannelEnabled: vi.fn(),
    onUpdateChannelField: vi.fn(),
    onSetExpandedChannel: vi.fn(),
    onSaveChannels: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

describe("ChannelsTab", () => {
  it("renders a tile for every channel", () => {
    render(<ChannelsTab {...makeProps()} />);
    for (const ch of ALL_CHANNELS) {
      expect(screen.getByText(CHANNEL_DISPLAY_NAMES[ch])).toBeInTheDocument();
    }
  });

  it("flags only enabled-but-unconfigured channels as needing setup", () => {
    render(<ChannelsTab {...makeProps()} />);
    // instagram (enabled, unconfigured) shows the warning; facebook
    // (configured) and teams (disabled) do not.
    expect(screen.getAllByText("Setup required")).toHaveLength(1);
  });

  it("renders the config fields for the expanded channel only", () => {
    render(<ChannelsTab {...makeProps({ expandedChannel: "instagram" })} />);
    expect(screen.getByText("Handle")).toBeInTheDocument();
    expect(screen.getByText("Business Account ID")).toBeInTheDocument();
    expect(screen.getByText("Access Token")).toBeInTheDocument();
    // Collapsed channels expose no inputs (facebook's Page ID field is absent)
    expect(screen.queryByText("Page ID")).not.toBeInTheDocument();
  });

  it("never displays a stored secret — sensitive inputs start empty and masked", () => {
    render(<ChannelsTab {...makeProps({ expandedChannel: "instagram" })} />);
    const tokenInput = screen.getByPlaceholderText("Meta access token");
    expect(tokenInput).toHaveAttribute("type", "password");
    expect(tokenInput).toHaveValue("");
    // Non-sensitive fields show the stored value
    expect(screen.getByPlaceholderText("@yourbrand")).toHaveValue("@naturespan");
  });

  it("shows the replace-hint placeholder for configured channels", () => {
    render(<ChannelsTab {...makeProps({ expandedChannel: "facebook" })} />);
    expect(
      screen.getByPlaceholderText("configured — enter new value to replace")
    ).toBeInTheDocument();
  });

  it("propagates non-sensitive field edits", () => {
    const props = makeProps({ expandedChannel: "instagram" });
    render(<ChannelsTab {...props} />);
    fireEvent.change(screen.getByPlaceholderText("@yourbrand"), {
      target: { value: "@newhandle" },
    });
    expect(props.onUpdateChannelField).toHaveBeenCalledWith("instagram", "handle", "@newhandle");
  });

  it("restores the mount value when a typed secret is cleared (accidental-clear guard)", () => {
    const props = makeProps({ expandedChannel: "instagram" });
    render(<ChannelsTab {...props} />);
    const tokenInput = screen.getByPlaceholderText("Meta access token");
    fireEvent.change(tokenInput, { target: { value: "new-secret" } });
    expect(props.onUpdateChannelField).toHaveBeenCalledWith(
      "instagram",
      "access_token",
      "new-secret"
    );
    fireEvent.change(tokenInput, { target: { value: "" } });
    expect(props.onUpdateChannelField).toHaveBeenLastCalledWith(
      "instagram",
      "access_token",
      "stored-token"
    );
  });

  it("disables Save while saving and calls onSaveChannels otherwise", () => {
    const props = makeProps();
    const { rerender } = render(<ChannelsTab {...props} />);
    const saveButton = screen.getByRole("button", { name: /save channel config/i });
    fireEvent.click(saveButton);
    expect(props.onSaveChannels).toHaveBeenCalledTimes(1);

    rerender(<ChannelsTab {...makeProps({ savingChannels: true })} />);
    expect(screen.getByRole("button", { name: /saving/i })).toBeDisabled();
  });
});
