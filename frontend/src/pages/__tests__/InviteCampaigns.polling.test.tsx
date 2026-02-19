import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, cleanup, act, waitFor } from "@testing-library/react";
import React from "react";
import type { InviteCampaign } from "../../types/invite";

/* ── Mocks ─────────────────────────────────────────────────────── */

const mockFetchInviteCampaigns = vi.fn<() => Promise<InviteCampaign[]>>();

vi.mock("../../services/inviteApi", () => ({
  fetchInviteCampaigns: (...args: unknown[]) => mockFetchInviteCampaigns(),
  fetchInviteCampaign: vi.fn(),
  createInviteCampaign: vi.fn(),
  startInviteCampaign: vi.fn(),
  pauseInviteCampaign: vi.fn(),
  resumeInviteCampaign: vi.fn(),
  fetchMyAdminChats: vi.fn(),
  fetchParsedContactsSummary: vi.fn(),
}));

vi.mock("../../services/resources", () => ({
  fetchTgAccounts: vi.fn(),
}));

vi.mock("../../stores/auth", () => ({
  useAuth: () => ({ token: "test-token" }),
}));

/* ── Helpers ───────────────────────────────────────────────────── */

function makeCampaign(overrides: Partial<InviteCampaign> = {}): InviteCampaign {
  return {
    id: 1,
    name: "Test Campaign",
    status: "draft",
    source_chat_id: 100,
    source_title: "Source",
    target_link: "https://t.me/test",
    target_title: "Target",
    max_invites_total: 100,
    invites_per_hour_per_account: 10,
    max_accounts: 2,
    invites_completed: 0,
    invites_failed: 0,
    created_at: "2025-01-01T00:00:00Z",
    ...overrides,
  };
}

/** Simulate document.hidden changing and fire visibilitychange */
function setDocumentHidden(hidden: boolean) {
  Object.defineProperty(document, "hidden", {
    value: hidden,
    writable: true,
    configurable: true,
  });
  act(() => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

/* ── Tests ─────────────────────────────────────────────────────── */

describe("InviteCampaigns — polling & page visibility", () => {
  let originalSetInterval: typeof globalThis.setInterval;
  let originalClearInterval: typeof globalThis.clearInterval;

  /** Track setInterval/clearInterval calls without replacing timer behavior */
  let intervalCalls: Array<{ id: number; delay: number }>;
  let clearedIds: number[];
  let nextId: number;

  beforeEach(() => {
    originalSetInterval = globalThis.setInterval;
    originalClearInterval = globalThis.clearInterval;
    intervalCalls = [];
    clearedIds = [];
    nextId = 9000;

    // Replace setInterval: record calls, return a fake id (don't actually schedule)
    globalThis.setInterval = vi.fn((_fn: unknown, delay?: number) => {
      const id = nextId++;
      intervalCalls.push({ id, delay: delay ?? 0 });
      return id as unknown as ReturnType<typeof setInterval>;
    }) as unknown as typeof globalThis.setInterval;

    // Replace clearInterval: record which ids were cleared
    globalThis.clearInterval = vi.fn((id?: unknown) => {
      if (id != null) clearedIds.push(id as number);
    }) as unknown as typeof globalThis.clearInterval;

    // Reset document.hidden to false (tab visible)
    Object.defineProperty(document, "hidden", {
      value: false,
      writable: true,
      configurable: true,
    });

    mockFetchInviteCampaigns.mockReset();
  });

  afterEach(() => {
    cleanup();
    globalThis.setInterval = originalSetInterval;
    globalThis.clearInterval = originalClearInterval;
  });

  /** Get all setInterval calls with 5000ms delay (list polling) */
  function pollingIntervals() {
    return intervalCalls.filter((c) => c.delay === 5000);
  }

  /** Active polling ids = created with 5s delay and not yet cleared */
  function activePollingIds() {
    const created = pollingIntervals().map((c) => c.id);
    return created.filter((id) => !clearedIds.includes(id));
  }

  it("does NOT start polling when there are no active campaigns", async () => {
    mockFetchInviteCampaigns.mockResolvedValue([makeCampaign({ status: "draft" })]);

    const { default: InviteCampaigns } = await import("../InviteCampaigns");

    await act(async () => {
      render(<InviteCampaigns />);
    });

    // Wait for the fetch promise to resolve and state to update
    await waitFor(() => {
      expect(mockFetchInviteCampaigns).toHaveBeenCalled();
    });

    // No setInterval with 5s delay should have been created
    expect(pollingIntervals()).toHaveLength(0);
  });

  it("starts polling when there is an active campaign", async () => {
    mockFetchInviteCampaigns.mockResolvedValue([makeCampaign({ status: "active" })]);

    const { default: InviteCampaigns } = await import("../InviteCampaigns");

    await act(async () => {
      render(<InviteCampaigns />);
    });

    await waitFor(() => {
      expect(pollingIntervals().length).toBeGreaterThanOrEqual(1);
    });

    // Should have at least one active polling interval
    expect(activePollingIds().length).toBeGreaterThanOrEqual(1);
  });

  it("stops polling when document becomes hidden", async () => {
    mockFetchInviteCampaigns.mockResolvedValue([makeCampaign({ status: "active" })]);

    const { default: InviteCampaigns } = await import("../InviteCampaigns");

    await act(async () => {
      render(<InviteCampaigns />);
    });

    // Wait until polling has started
    await waitFor(() => {
      expect(activePollingIds().length).toBeGreaterThanOrEqual(1);
    });

    // Tab goes hidden → clearInterval should fire and remove the active interval
    setDocumentHidden(true);

    expect(activePollingIds()).toHaveLength(0);
  });

  it("restores polling when document becomes visible with active campaigns", async () => {
    mockFetchInviteCampaigns.mockResolvedValue([makeCampaign({ status: "active" })]);

    const { default: InviteCampaigns } = await import("../InviteCampaigns");

    await act(async () => {
      render(<InviteCampaigns />);
    });

    await waitFor(() => {
      expect(activePollingIds().length).toBeGreaterThanOrEqual(1);
    });

    // Hide → stops polling
    setDocumentHidden(true);
    expect(activePollingIds()).toHaveLength(0);

    // Show → should create a new interval
    setDocumentHidden(false);
    expect(activePollingIds().length).toBeGreaterThanOrEqual(1);
  });

  it("does NOT restore polling when document becomes visible without active campaigns", async () => {
    mockFetchInviteCampaigns.mockResolvedValue([makeCampaign({ status: "completed" })]);

    const { default: InviteCampaigns } = await import("../InviteCampaigns");

    await act(async () => {
      render(<InviteCampaigns />);
    });

    await waitFor(() => {
      expect(mockFetchInviteCampaigns).toHaveBeenCalled();
    });

    // No polling should have been created (no active campaigns)
    expect(pollingIntervals()).toHaveLength(0);

    // Hide then show — still no polling
    setDocumentHidden(true);
    setDocumentHidden(false);

    expect(pollingIntervals()).toHaveLength(0);
  });
});
