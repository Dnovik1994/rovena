import React, { useMemo, useState } from "react";

import { getTelegramDebugInfo, isTelegramWebApp } from "../utils/telegram";

interface TelegramWebAppGuardProps {
  children: React.ReactNode;
}

const TelegramWebAppGuard = ({ children }: TelegramWebAppGuardProps): JSX.Element => {
  const hasTelegram = isTelegramWebApp();
  const hasDevInitData = import.meta.env.DEV && Boolean(import.meta.env.VITE_TG_INIT_DATA);
  const debugEnabled = useMemo(() => {
    const searchParams = new URLSearchParams(window.location.search);
    return import.meta.env.DEV || searchParams.get("debug") === "1";
  }, []);
  const [showDebug, setShowDebug] = useState(debugEnabled);

  const debugInfo = debugEnabled ? getTelegramDebugInfo() : null;
  const isDev = import.meta.env.DEV;
  const mask = (v: string | undefined | null) => (isDev ? (v ?? "N/A") : "***");
  const debugRows = debugEnabled
    ? [
        { label: "userAgent", value: navigator.userAgent },
        { label: "current URL", value: window.location.href },
        { label: "isTelegramWebApp", value: String(debugInfo?.isTelegramWebApp ?? false) },
        { label: "initData length", value: String(debugInfo?.initDataLength ?? 0) },
        { label: "initDataUnsafe keys", value: String(debugInfo?.initDataUnsafeKeys ?? 0) },
        { label: "user id", value: mask(debugInfo?.userId) },
        { label: "auth_date", value: mask(debugInfo?.authDate) },
        { label: "query_id", value: mask(debugInfo?.queryId) },
      ]
    : [];
  const telegramType = typeof window.Telegram;

  if (hasTelegram) {
    return (
      <>
        {debugEnabled && (
          <div className="fixed right-4 top-4 z-50 flex flex-col items-end gap-2">
            <button
              type="button"
              className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1 text-xs text-slate-200"
              onClick={() => setShowDebug((prev) => !prev)}
            >
              {showDebug ? "Hide debug" : "Show debug"}
            </button>
            {showDebug && (
              <div className="w-80 rounded-lg border border-slate-700 bg-slate-900 p-3 text-left text-xs text-slate-300">
                <p className="mb-2 font-semibold text-slate-200">Debug</p>
                <table className="w-full">
                  <tbody>
                    {debugRows.map((row) => (
                      <tr key={row.label}>
                        <td className="pr-2 text-slate-500">{row.label}</td>
                        <td className="break-all">{row.value}</td>
                      </tr>
                    ))}
                    <tr>
                      <td className="pr-2 text-slate-500">typeof window.Telegram</td>
                      <td className="break-all">{telegramType}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
        {children}
      </>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <section className="mx-auto flex max-w-2xl flex-col gap-4 px-4 py-12 text-center">
        <h1 className="text-2xl font-semibold">Telegram WebApp</h1>
        <p className="text-sm text-slate-300">
          Open this app from Telegram via the bot’s Menu Button or a web_app keyboard button.
          Direct URL in browser won’t provide initData.
        </p>
        {hasDevInitData && (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-300">
            Local development fallback detected (VITE_TG_INIT_DATA). The app will render below,
            but production must be launched from Telegram.
          </div>
        )}
        {debugEnabled && (
          <button
            type="button"
            className="mx-auto rounded-lg border border-slate-700 px-3 py-1 text-xs text-slate-300"
            onClick={() => setShowDebug((prev) => !prev)}
          >
            {showDebug ? "Hide debug" : "Show debug"}
          </button>
        )}
        {debugEnabled && showDebug && (
          <div className="rounded-lg border border-slate-700 bg-slate-900 p-4 text-left text-xs text-slate-400">
            <p className="mb-2 font-semibold text-slate-300">Debug</p>
            <table className="w-full">
              <tbody>
                {debugRows.map((row) => (
                  <tr key={row.label}>
                    <td className="pr-2 text-slate-500">{row.label}</td>
                    <td className="break-all">{row.value}</td>
                  </tr>
                ))}
                <tr>
                  <td className="pr-2 text-slate-500">typeof window.Telegram</td>
                  <td className="break-all">{telegramType}</td>
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </section>
      {hasDevInitData && <div className="min-h-screen">{children}</div>}
    </div>
  );
};

export default TelegramWebAppGuard;
