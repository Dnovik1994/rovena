interface TelegramWebApp {
  initData: string;
  platform: string;
  version: string;
  themeParams?: Record<string, string>;
  ready: () => void;
  onEvent: (event: string, handler: () => void) => void;
  offEvent: (event: string, handler: () => void) => void;
}

interface TelegramGlobal {
  WebApp?: TelegramWebApp;
}

declare global {
  interface Window {
    Telegram?: TelegramGlobal;
  }
}

export function getTelegramWebApp(): TelegramWebApp | undefined {
  return window.Telegram?.WebApp;
}

export function isTelegramWebApp(): boolean {
  return !!window.Telegram?.WebApp;
}

export function getInitData(): string {
  const webapp = getTelegramWebApp();
  if (webapp?.initData) {
    return webapp.initData;
  }
  if (!webapp) {
    return import.meta.env.VITE_TG_INIT_DATA || "";
  }
  return "";
}

export type InitDataStatus =
  | { kind: "ok"; initData: string }
  | { kind: "no_telegram" }
  | { kind: "empty_init_data" };

export function diagnoseInitData(): InitDataStatus {
  const webapp = getTelegramWebApp();
  if (!webapp) {
    const fallback = import.meta.env.VITE_TG_INIT_DATA;
    if (fallback) {
      return { kind: "ok", initData: fallback };
    }
    return { kind: "no_telegram" };
  }
  if (!webapp.initData) {
    return { kind: "empty_init_data" };
  }
  return { kind: "ok", initData: webapp.initData };
}

export interface TelegramDebugInfo {
  isTelegramWebApp: boolean;
  initDataLength: number;
  platform: string;
  version: string;
}

export function getTelegramDebugInfo(): TelegramDebugInfo {
  const webapp = getTelegramWebApp();
  return {
    isTelegramWebApp: !!webapp,
    initDataLength: webapp?.initData?.length ?? 0,
    platform: webapp?.platform ?? "N/A",
    version: webapp?.version ?? "N/A",
  };
}
