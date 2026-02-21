import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import AdminWarmingTab from "../AdminWarmingTab";

// ── Mock apiFetch ───────────────────────────────────────────────────

const mockApiFetch = vi.fn();

vi.mock("../../../shared/api/client", () => ({
  apiFetch: (...args: unknown[]) => mockApiFetch(...args),
  API_BASE_URL: "/api/v1",
}));

// ── Helpers ─────────────────────────────────────────────────────────

function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

function renderWithProviders() {
  const qc = createQueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <AdminWarmingTab token="test-token" />
    </QueryClientProvider>,
  );
}

// ── Setup / Teardown ────────────────────────────────────────────────

beforeEach(() => {
  mockApiFetch.mockReset();
  // Default: return empty arrays for list queries
  mockApiFetch.mockResolvedValue([]);
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ═══════════════════════════════════════════════════════════════════
// Tests
// ═══════════════════════════════════════════════════════════════════

describe("AdminWarmingTab", () => {
  it("renders all 6 subtabs", async () => {
    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByText("Channels")).toBeInTheDocument();
    });
    expect(screen.getByText("Bios")).toBeInTheDocument();
    expect(screen.getByText("Photos")).toBeInTheDocument();
    expect(screen.getByText("Usernames")).toBeInTheDocument();
    expect(screen.getByText("Names")).toBeInTheDocument();
    expect(screen.getByText("Notifications")).toBeInTheDocument();
  });

  it("add channel sends POST request", async () => {
    const user = userEvent.setup();
    mockApiFetch
      .mockResolvedValueOnce([]) // GET /channels
      .mockResolvedValueOnce({
        id: 1,
        username: "new_channel",
        channel_type: "channel",
        language: "en",
        is_active: true,
      }) // POST /channels
      .mockResolvedValue([]); // subsequent GETs

    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByText("Add channel")).toBeInTheDocument();
    });

    await user.click(screen.getByText("Add channel"));

    const usernameInput = screen.getByRole("textbox");
    await user.type(usernameInput, "new_channel");

    await user.click(screen.getByText("Save"));

    await waitFor(() => {
      const postCall = mockApiFetch.mock.calls.find((call) => {
        const opts = call[1] as RequestInit | undefined;
        return opts?.method === "POST";
      });
      expect(postCall).toBeDefined();
      expect(postCall![0]).toContain("/channels");
    });
  });

  it("delete shows confirmation dialog", async () => {
    const user = userEvent.setup();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

    mockApiFetch.mockResolvedValueOnce([
      { id: 1, username: "ch1", type: "channel", language: "en", is_active: true },
    ]);

    renderWithProviders();

    await waitFor(() => {
      expect(screen.getByText("ch1")).toBeInTheDocument();
    });

    const deleteBtn = screen.getByText("Delete");
    await user.click(deleteBtn);

    expect(confirmSpy).toHaveBeenCalledWith("Delete this item?");
  });

  it("notification toggle sends PATCH request", async () => {
    const user = userEvent.setup();

    // Route mock responses based on the path argument
    mockApiFetch.mockImplementation((path: string, opts?: RequestInit) => {
      if (path.includes("/notifications") && opts?.method === "PATCH") {
        return Promise.resolve({
          id: 10,
          chat_id: "-1001234",
          on_ban: true,
          on_flood_wait: true,
          on_warming_done: true,
          on_error: true,
        });
      }
      if (path.includes("/notifications")) {
        return Promise.resolve([
          {
            id: 10,
            chat_id: "-1001234",
            on_ban: true,
            on_flood_wait: true,
            on_warming_done: true,
            on_error: false,
          },
        ]);
      }
      // Default: channels, bios, etc.
      return Promise.resolve([]);
    });

    renderWithProviders();

    // Wait for the initial tab to load, then switch to Notifications
    await waitFor(() => {
      expect(screen.getByText("Notifications")).toBeInTheDocument();
    });

    await user.click(screen.getByText("Notifications"));

    // Wait for notifications data to render
    await waitFor(() => {
      expect(screen.getByText("Chat: -1001234")).toBeInTheDocument();
    });

    // Find the unchecked checkbox (on_error is false)
    const checkboxes = screen.getAllByRole("checkbox");
    const uncheckedBox = checkboxes.find(
      (cb) => !(cb as HTMLInputElement).checked,
    );
    expect(uncheckedBox).toBeDefined();

    await user.click(uncheckedBox!);

    await waitFor(() => {
      const patchCall = mockApiFetch.mock.calls.find((call) => {
        const opts = call[1] as RequestInit | undefined;
        return opts?.method === "PATCH";
      });
      expect(patchCall).toBeDefined();
      expect(patchCall![0]).toContain("/notifications/");
    });
  });
});
