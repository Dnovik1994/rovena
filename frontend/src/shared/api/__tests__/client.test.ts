import { afterAll, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../utils/authStorage", () => ({
  getStoredTokens: vi.fn(),
  setStoredTokens: vi.fn(),
  clearStoredTokens: vi.fn(),
  parseJwtExpiry: vi.fn(),
}));

import { apiFetch, API_BASE_URL, _resetRefreshPromise } from "../client";
import {
  clearStoredTokens,
  getStoredTokens,
  parseJwtExpiry,
  setStoredTokens,
} from "../../../utils/authStorage";

/* ── Helpers ──────────────────────────────────────────────── */

function mockResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    headers: new Headers({ "content-type": "application/json" }),
    json: () => Promise.resolve(body),
    text: () =>
      Promise.resolve(body != null ? JSON.stringify(body) : ""),
  } as unknown as Response;
}

/* ── Setup / Teardown ─────────────────────────────────────── */

const originalFetch = global.fetch;
const mockedFetch = vi.fn<typeof fetch>();

beforeEach(() => {
  mockedFetch.mockReset();
  global.fetch = mockedFetch;
  _resetRefreshPromise();

  vi.mocked(getStoredTokens).mockReturnValue({
    accessToken: "old-access",
    refreshToken: "valid-refresh",
    accessTokenExpiresAt: null,
  });
  vi.mocked(parseJwtExpiry).mockReturnValue(Date.now() + 3_600_000);
  vi.mocked(setStoredTokens).mockReset();
  vi.mocked(clearStoredTokens).mockReset();
});

afterAll(() => {
  global.fetch = originalFetch;
});

/* ── Tests ────────────────────────────────────────────────── */

describe("apiFetch", () => {
  it("returns data on successful request", async () => {
    const payload = { id: 1, name: "Alice" };
    mockedFetch.mockResolvedValueOnce(mockResponse(payload));

    const result = await apiFetch<typeof payload>("/users/1");

    expect(result).toEqual(payload);
    expect(mockedFetch).toHaveBeenCalledOnce();

    const [url, init] = mockedFetch.mock.calls[0];
    expect(url).toBe(`${API_BASE_URL}/users/1`);
    expect((init!.headers as Headers).get("Authorization")).toBe(
      "Bearer old-access",
    );
  });

  it("refreshes token on 401, retries with new token", async () => {
    const payload = { ok: true };

    // original → 401
    mockedFetch.mockResolvedValueOnce(
      mockResponse(
        { error: { code: "UNAUTHORIZED", message: "expired" } },
        401,
      ),
    );
    // refresh → new tokens
    mockedFetch.mockResolvedValueOnce(
      mockResponse({
        access_token: "new-access",
        refresh_token: "new-refresh",
      }),
    );
    // retry → success
    mockedFetch.mockResolvedValueOnce(mockResponse(payload));

    const result = await apiFetch("/data");

    expect(result).toEqual(payload);
    expect(mockedFetch).toHaveBeenCalledTimes(3);

    // refresh called with correct body
    const [refreshUrl, refreshInit] = mockedFetch.mock.calls[1];
    expect(refreshUrl).toBe(`${API_BASE_URL}/auth/refresh`);
    expect(JSON.parse(refreshInit!.body as string)).toEqual({
      refresh_token: "valid-refresh",
    });

    // retry used the new token
    const retryHeaders = mockedFetch.mock.calls[2][1]!.headers as Headers;
    expect(retryHeaders.get("Authorization")).toBe("Bearer new-access");

    // tokens were persisted
    expect(setStoredTokens).toHaveBeenCalledWith({
      accessToken: "new-access",
      refreshToken: "new-refresh",
      accessTokenExpiresAt: expect.any(Number),
    });
  });

  it("does not loop when refresh also fails", async () => {
    // original → 401
    mockedFetch.mockResolvedValueOnce(mockResponse({}, 401));
    // refresh → 401 too
    mockedFetch.mockResolvedValueOnce(mockResponse({}, 401));

    await expect(apiFetch("/protected")).rejects.toMatchObject({
      status: 401,
    });

    // 2 calls only: original + refresh attempt. No infinite retry.
    expect(mockedFetch).toHaveBeenCalledTimes(2);
    expect(clearStoredTokens).toHaveBeenCalled();
  });

  it("two parallel 401s deduplicate into a single refresh call", async () => {
    const hitCount: Record<string, number> = {};

    mockedFetch.mockImplementation(async (input) => {
      const url = String(input);

      if (url.includes("/auth/refresh")) {
        return mockResponse({
          access_token: "new-access",
          refresh_token: "new-refresh",
        });
      }

      hitCount[url] = (hitCount[url] || 0) + 1;

      // first call per endpoint → 401; second (retry) → 200
      if (hitCount[url] === 1) return mockResponse({}, 401);
      return url.includes("/ep1")
        ? mockResponse({ data: "one" })
        : mockResponse({ data: "two" });
    });

    const [r1, r2] = await Promise.all([
      apiFetch<{ data: string }>("/ep1"),
      apiFetch<{ data: string }>("/ep2"),
    ]);

    expect(r1).toEqual({ data: "one" });
    expect(r2).toEqual({ data: "two" });

    // Only one refresh call — deduplication works
    const refreshCount = mockedFetch.mock.calls.filter(([u]) =>
      String(u).includes("/auth/refresh"),
    ).length;
    expect(refreshCount).toBe(1);
  });

  it("throws NETWORK error when fetch rejects", async () => {
    mockedFetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await expect(apiFetch("/data")).rejects.toMatchObject({
      code: "NETWORK",
      message: "Ошибка сети. Проверьте подключение.",
    });

    expect(mockedFetch).toHaveBeenCalledOnce();
  });
});
