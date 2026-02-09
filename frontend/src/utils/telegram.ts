interface TelegramWebApp {
  initData: string;
  initDataUnsafe: Record<string, unknown>;
  platform: string;
  version: string;
  themeParams?: Record<string, string>;
  expand?: () => void;
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
    return import.meta.env.DEV ? import.meta.env.VITE_TG_INIT_DATA || "" : "";
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
    const fallback = import.meta.env.DEV ? import.meta.env.VITE_TG_INIT_DATA : "";
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
  initDataUnsafeKeys: number;
  userId: string;
  authDate: string;
  queryId: string;
  platform: string;
  version: string;
}

export function getTelegramDebugInfo(): TelegramDebugInfo {
  const webapp = getTelegramWebApp();
  const initDataUnsafe = webapp?.initDataUnsafe as
    | {
        user?: { id?: number | string };
        auth_date?: number | string;
        query_id?: string;
      }
    | undefined;
  return {
    isTelegramWebApp: !!webapp,
    initDataLength: webapp?.initData?.length ?? 0,
    initDataUnsafeKeys: webapp?.initDataUnsafe ? Object.keys(webapp.initDataUnsafe).length : 0,
    userId: initDataUnsafe?.user?.id ? String(initDataUnsafe.user.id) : "N/A",
    authDate: initDataUnsafe?.auth_date ? String(initDataUnsafe.auth_date) : "N/A",
    queryId: initDataUnsafe?.query_id ?? "N/A",
    platform: webapp?.platform ?? "N/A",
    version: webapp?.version ?? "N/A",
  };
}
