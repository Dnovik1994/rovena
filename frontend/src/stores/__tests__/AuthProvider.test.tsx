import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { AuthProvider, useAuth } from "../auth";

/* ── Test consumer ────────────────────────────────────────── */

function TestConsumer() {
  const auth = useAuth();
  return (
    <div>
      <div data-testid="token">{auth.token ?? ""}</div>
      <div data-testid="refreshToken">{auth.refreshToken ?? ""}</div>
      <button data-testid="logout" onClick={auth.logout}>
        logout
      </button>
      <button
        data-testid="setToken"
        onClick={() => auth.setToken("new-access", "new-refresh", 9999)}
      >
        setToken
      </button>
    </div>
  );
}

function renderWithAuth() {
  return render(
    <AuthProvider>
      <TestConsumer />
    </AuthProvider>,
  );
}

/* ── Setup / Teardown ─────────────────────────────────────── */

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
});

/* ── Tests ─────────────────────────────────────────────────── */

describe("AuthProvider", () => {
  it("reads token from localStorage on mount — children render, token is not null", () => {
    localStorage.setItem("access_token", "stored-access");
    localStorage.setItem("refresh_token", "stored-refresh");

    renderWithAuth();

    expect(screen.getByTestId("token").textContent).toBe("stored-access");
    expect(screen.getByTestId("refreshToken").textContent).toBe("stored-refresh");
  });

  it("token is null when localStorage is empty", () => {
    renderWithAuth();

    expect(screen.getByTestId("token").textContent).toBe("");
    expect(screen.getByTestId("refreshToken").textContent).toBe("");
  });

  it("logout() clears tokens from localStorage and sets token to null", () => {
    localStorage.setItem("access_token", "a");
    localStorage.setItem("refresh_token", "r");
    localStorage.setItem("access_token_expires_at", "123");

    renderWithAuth();

    expect(screen.getByTestId("token").textContent).toBe("a");

    act(() => {
      screen.getByTestId("logout").click();
    });

    expect(screen.getByTestId("token").textContent).toBe("");
    expect(screen.getByTestId("refreshToken").textContent).toBe("");

    expect(localStorage.getItem("access_token")).toBeNull();
    expect(localStorage.getItem("refresh_token")).toBeNull();
    expect(localStorage.getItem("access_token_expires_at")).toBeNull();
  });

  it("setToken(newToken) updates token in context", () => {
    renderWithAuth();

    expect(screen.getByTestId("token").textContent).toBe("");

    act(() => {
      screen.getByTestId("setToken").click();
    });

    expect(screen.getByTestId("token").textContent).toBe("new-access");
    expect(screen.getByTestId("refreshToken").textContent).toBe("new-refresh");

    expect(localStorage.getItem("access_token")).toBe("new-access");
    expect(localStorage.getItem("refresh_token")).toBe("new-refresh");
  });

  it("syncs state when external auth:tokens event fires", async () => {
    renderWithAuth();

    expect(screen.getByTestId("token").textContent).toBe("");

    act(() => {
      localStorage.setItem("access_token", "external-access");
      localStorage.setItem("refresh_token", "external-refresh");
      window.dispatchEvent(new Event("auth:tokens"));
    });

    expect(screen.getByTestId("token").textContent).toBe("external-access");
    expect(screen.getByTestId("refreshToken").textContent).toBe("external-refresh");
  });

  it("useAuth throws when used outside AuthProvider", () => {
    expect(() => render(<TestConsumer />)).toThrow(
      "useAuth must be used within AuthProvider",
    );
  });
});
