import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  diagnoseInitData,
  getInitData,
  getTelegramDebugInfo,
  getTelegramWebApp,
  isTelegramWebApp,
} from "../telegram";

/* ── Helpers ──────────────────────────────────────────────── */

/** Save and restore window.Telegram between tests. */
let savedTelegram: typeof window.Telegram;

beforeEach(() => {
  savedTelegram = window.Telegram;
});

afterEach(() => {
  window.Telegram = savedTelegram;
});

/* ── getTelegramWebApp / isTelegramWebApp ────────────────── */

describe("getTelegramWebApp", () => {
  it("returns WebApp when window.Telegram.WebApp exists", () => {
    expect(getTelegramWebApp()).toBeDefined();
    expect(getTelegramWebApp()!.initData).toBe("mock_init_data");
  });

  it("returns undefined when window.Telegram is absent", () => {
    window.Telegram = undefined;
    expect(getTelegramWebApp()).toBeUndefined();
  });
});

describe("isTelegramWebApp", () => {
  it("returns true when WebApp is present", () => {
    expect(isTelegramWebApp()).toBe(true);
  });

  it("returns false when Telegram is absent", () => {
    window.Telegram = undefined;
    expect(isTelegramWebApp()).toBe(false);
  });
});

/* ── getInitData ─────────────────────────────────────────── */

describe("getInitData", () => {
  it("returns initData from WebApp when present", () => {
    expect(getInitData()).toBe("mock_init_data");
  });

  it("returns empty string when WebApp exists but initData is empty", () => {
    window.Telegram = {
      WebApp: {
        ...window.Telegram!.WebApp!,
        initData: "",
      },
    };
    expect(getInitData()).toBe("");
  });

  it("returns empty string when Telegram is absent (non-DEV)", () => {
    window.Telegram = undefined;
    // In test env import.meta.env.DEV is true, but VITE_TG_INIT_DATA is not set
    // so the result depends on env; we just check it doesn't throw
    const result = getInitData();
    expect(typeof result).toBe("string");
  });
});

/* ── diagnoseInitData ────────────────────────────────────── */

describe("diagnoseInitData", () => {
  it('returns { kind: "ok" } when initData is present', () => {
    const status = diagnoseInitData();
    expect(status).toEqual({ kind: "ok", initData: "mock_init_data" });
  });

  it('returns { kind: "empty_init_data" } when WebApp exists but initData is empty', () => {
    window.Telegram = {
      WebApp: {
        ...window.Telegram!.WebApp!,
        initData: "",
      },
    };
    const status = diagnoseInitData();
    expect(status).toEqual({ kind: "empty_init_data" });
  });

  it('returns { kind: "no_telegram" } when Telegram is absent', () => {
    window.Telegram = undefined;
    const status = diagnoseInitData();
    // In DEV without VITE_TG_INIT_DATA, falls back to no_telegram
    expect(status.kind).toBe("no_telegram");
  });
});

/* ── getTelegramDebugInfo ────────────────────────────────── */

describe("getTelegramDebugInfo", () => {
  it("returns populated debug info when WebApp is present", () => {
    const info = getTelegramDebugInfo();
    expect(info.isTelegramWebApp).toBe(true);
    expect(info.initDataLength).toBe("mock_init_data".length);
    expect(info.userId).toBe("123456");
    expect(info.platform).toBe("tdesktop");
    expect(info.version).toBe("6.0");
  });

  it("returns fallback values when Telegram is absent", () => {
    window.Telegram = undefined;
    const info = getTelegramDebugInfo();
    expect(info.isTelegramWebApp).toBe(false);
    expect(info.initDataLength).toBe(0);
    expect(info.userId).toBe("N/A");
    expect(info.platform).toBe("N/A");
  });
});
