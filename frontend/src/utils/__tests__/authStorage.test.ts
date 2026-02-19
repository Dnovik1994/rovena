import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearStoredTokens,
  getStoredTokens,
  onTokensChanged,
  parseJwtExpiry,
  setStoredTokens,
  StoredTokens,
} from "../authStorage";

/* ── Helpers ──────────────────────────────────────────────── */

/** Build a minimal JWT with the given payload. */
function fakeJwt(payload: Record<string, unknown>): string {
  const header = btoa(JSON.stringify({ alg: "HS256" }));
  const body = btoa(JSON.stringify(payload));
  return `${header}.${body}.signature`;
}

/* ── Setup / Teardown ─────────────────────────────────────── */

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
});

/* ── parseJwtExpiry ───────────────────────────────────────── */

describe("parseJwtExpiry", () => {
  it("returns exp * 1000 for a valid JWT with exp claim", () => {
    const exp = 1700000000;
    const token = fakeJwt({ exp });
    expect(parseJwtExpiry(token)).toBe(exp * 1000);
  });

  it("returns null when exp claim is missing", () => {
    const token = fakeJwt({ sub: "user123" });
    expect(parseJwtExpiry(token)).toBeNull();
  });

  it("returns null when exp is not a number", () => {
    const token = fakeJwt({ exp: "not-a-number" });
    expect(parseJwtExpiry(token)).toBeNull();
  });

  it("returns null for a malformed token (not 3 parts)", () => {
    expect(parseJwtExpiry("not-a-jwt")).toBeNull();
  });

  it("returns null for a token with invalid base64 payload", () => {
    expect(parseJwtExpiry("header.!!!invalid!!!.signature")).toBeNull();
  });
});

/* ── getStoredTokens / setStoredTokens ───────────────────── */

describe("getStoredTokens & setStoredTokens", () => {
  it("returns nulls when localStorage is empty", () => {
    expect(getStoredTokens()).toEqual({
      accessToken: null,
      refreshToken: null,
      accessTokenExpiresAt: null,
    });
  });

  it("round-trips tokens through localStorage", () => {
    const tokens: StoredTokens = {
      accessToken: "access-abc",
      refreshToken: "refresh-xyz",
      accessTokenExpiresAt: 1700000000000,
    };
    setStoredTokens(tokens);
    expect(getStoredTokens()).toEqual(tokens);
  });

  it("removes keys when token values are null", () => {
    setStoredTokens({
      accessToken: "a",
      refreshToken: "r",
      accessTokenExpiresAt: 123,
    });

    setStoredTokens({
      accessToken: null,
      refreshToken: null,
      accessTokenExpiresAt: null,
    });

    expect(localStorage.getItem("access_token")).toBeNull();
    expect(localStorage.getItem("refresh_token")).toBeNull();
    expect(localStorage.getItem("access_token_expires_at")).toBeNull();
  });

  it("dispatches auth:tokens event when tokens are set", () => {
    const handler = vi.fn();
    window.addEventListener("auth:tokens", handler);

    setStoredTokens({
      accessToken: "t",
      refreshToken: "r",
      accessTokenExpiresAt: null,
    });

    expect(handler).toHaveBeenCalledOnce();
    window.removeEventListener("auth:tokens", handler);
  });
});

/* ── clearStoredTokens ───────────────────────────────────── */

describe("clearStoredTokens", () => {
  it("removes all stored tokens", () => {
    setStoredTokens({
      accessToken: "a",
      refreshToken: "r",
      accessTokenExpiresAt: 999,
    });

    clearStoredTokens();

    expect(getStoredTokens()).toEqual({
      accessToken: null,
      refreshToken: null,
      accessTokenExpiresAt: null,
    });
  });
});

/* ── onTokensChanged ─────────────────────────────────────── */

describe("onTokensChanged", () => {
  it("calls handler when tokens change", () => {
    const handler = vi.fn();
    const unsubscribe = onTokensChanged(handler);

    setStoredTokens({
      accessToken: "new",
      refreshToken: null,
      accessTokenExpiresAt: null,
    });

    expect(handler).toHaveBeenCalledOnce();
    unsubscribe();
  });

  it("stops calling handler after unsubscribe", () => {
    const handler = vi.fn();
    const unsubscribe = onTokensChanged(handler);
    unsubscribe();

    setStoredTokens({
      accessToken: "new",
      refreshToken: null,
      accessTokenExpiresAt: null,
    });

    expect(handler).not.toHaveBeenCalled();
  });
});
