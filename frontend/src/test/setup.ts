import { vi } from "vitest";
import "@testing-library/jest-dom/vitest";

/* ── Mock window.Telegram.WebApp ─────────────────────────────── */

const telegramWebApp = {
  initData: "mock_init_data",
  initDataUnsafe: {
    user: {
      id: 123456,
      first_name: "Test",
      last_name: "User",
      username: "testuser",
      language_code: "en",
    },
    auth_date: Math.floor(Date.now() / 1000),
    hash: "mock_hash",
  },
  ready: vi.fn(),
  expand: vi.fn(),
  close: vi.fn(),
  MainButton: {
    text: "",
    isVisible: false,
    show: vi.fn(),
    hide: vi.fn(),
    onClick: vi.fn(),
    offClick: vi.fn(),
  },
  themeParams: {
    bg_color: "#1a1a2e",
    text_color: "#ffffff",
    hint_color: "#999999",
    link_color: "#6c63ff",
    button_color: "#6c63ff",
    button_text_color: "#ffffff",
  },
  colorScheme: "dark" as const,
  platform: "tdesktop",
  version: "6.0",
};

Object.defineProperty(window, "Telegram", {
  value: { WebApp: telegramWebApp },
  writable: true,
});

/* ── Mock matchMedia ─────────────────────────────────────────── */

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});
