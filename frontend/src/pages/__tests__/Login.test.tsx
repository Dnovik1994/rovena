import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";

import { renderWithProviders } from "../../test/renderWithProviders";
import Login from "../Login";

/* ── Helpers ────────────────────────────────────────────────── */

function fakeJwt(payload: Record<string, unknown>): string {
  const h = btoa(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const p = btoa(JSON.stringify(payload));
  return `${h}.${p}.sig`;
}

const ACCESS_TOKEN = fakeJwt({ sub: "1", exp: Math.floor(Date.now() / 1000) + 3600 });
const REFRESH_TOKEN = "refresh_abc";

function jsonResponse(status: number, body: Record<string, unknown>): Response {
  const raw = JSON.stringify(body);
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status >= 500 ? "Internal Server Error" : "OK",
    headers: new Headers({
      "content-type": "application/json",
      "content-length": String(raw.length),
    }),
    json: async () => body,
    text: async () => raw,
  } as unknown as Response;
}

/* ── Tests ──────────────────────────────────────────────────── */

describe("Login", () => {
  beforeEach(() => {
    localStorage.clear();
    // Telegram WebApp is set globally in setup.ts; ensure initData is present
    (window as any).Telegram.WebApp.initData = "mock_init_data";
  });

  afterEach(() => {
    vi.restoreAllMocks();
    cleanup();
  });

  /* ── 1. POST /auth/telegram called with initData ──────────── */

  it("sends POST /auth/telegram with initData on click", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue(
      jsonResponse(200, { access_token: ACCESS_TOKEN, refresh_token: REFRESH_TOKEN }),
    );

    renderWithProviders(<Login />);
    await user.click(screen.getByRole("button", { name: /войти/i }));

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1));

    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toContain("/auth/telegram");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init!.body as string)).toEqual({ init_data: "mock_init_data" });
  });

  /* ── 2. Tokens saved to localStorage ─────────────────────── */

  it("saves tokens to localStorage on successful auth", async () => {
    const user = userEvent.setup();
    vi.spyOn(global, "fetch").mockResolvedValue(
      jsonResponse(200, { access_token: ACCESS_TOKEN, refresh_token: REFRESH_TOKEN }),
    );

    renderWithProviders(<Login />);
    await user.click(screen.getByRole("button", { name: /войти/i }));

    await waitFor(() => {
      expect(localStorage.getItem("access_token")).toBe(ACCESS_TOKEN);
      expect(localStorage.getItem("refresh_token")).toBe(REFRESH_TOKEN);
    });
  });

  /* ── 3. Successful auth with onboarding — no error shown ── */

  it("completes login without error when onboarding_needed is set", async () => {
    const user = userEvent.setup();
    vi.spyOn(global, "fetch").mockResolvedValue(
      jsonResponse(200, {
        access_token: ACCESS_TOKEN,
        refresh_token: REFRESH_TOKEN,
        onboarding_needed: true,
      }),
    );

    renderWithProviders(<Login />);
    await user.click(screen.getByRole("button", { name: /войти/i }));

    await waitFor(() => {
      expect(localStorage.getItem("access_token")).toBe(ACCESS_TOKEN);
    });
    // No error — setToken + setOnboardingNeeded were called,
    // actual redirect to /onboarding is handled by AppRoutes
    expect(screen.queryByText(/не удалось войти/i)).not.toBeInTheDocument();
  });

  /* ── 4. Server 500 → error message ────────────────────────── */

  it("shows error message on server 500 response", async () => {
    const user = userEvent.setup();

    // Prevent jsdom navigation triggered by apiFetch's 5xx redirect logic.
    // Save the original descriptor so we can restore it after the test.
    const origDescriptor = Object.getOwnPropertyDescriptor(window, "location")!;
    Object.defineProperty(window, "location", {
      value: { pathname: "/", href: "http://localhost:3000/", search: "", hash: "" },
      configurable: true,
      writable: true,
    });

    vi.spyOn(global, "fetch").mockResolvedValue(
      jsonResponse(500, { error: { code: "SERVER_ERROR", message: "fail" } }),
    );

    renderWithProviders(<Login />);
    await user.click(screen.getByRole("button", { name: /войти/i }));

    await waitFor(() => {
      expect(screen.getByText(/не удалось войти/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/500/)).toBeInTheDocument();

    // Restore original jsdom location
    Object.defineProperty(window, "location", origDescriptor);
  });

  /* ── 5. Empty initData → error ────────────────────────────── */

  it("shows error when Telegram initData is empty", async () => {
    const user = userEvent.setup();
    (window as any).Telegram.WebApp.initData = "";

    renderWithProviders(<Login />);
    await user.click(screen.getByRole("button", { name: /войти/i }));

    await waitFor(() => {
      expect(screen.getByText(/initData пуст/i)).toBeInTheDocument();
    });
  });

  /* ── 6. Loading state ─────────────────────────────────────── */

  it("disables button and shows loading text while request is in flight", async () => {
    const user = userEvent.setup();
    // fetch that never resolves — simulates in-flight request
    vi.spyOn(global, "fetch").mockReturnValue(new Promise(() => {}));

    renderWithProviders(<Login />);
    await user.click(screen.getByRole("button", { name: /войти/i }));

    const btn = screen.getByRole("button", { name: /подключаем/i });
    expect(btn).toBeDisabled();
  });
});
