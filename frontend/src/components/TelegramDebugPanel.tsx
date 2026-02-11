import React from "react";
import { getTelegramDebugInfo } from "../utils/telegram";

const TelegramDebugPanel = (): JSX.Element | null => {
  const searchParams = new URLSearchParams(window.location.search);
  const isDebugEnabled = import.meta.env.DEV || searchParams.get("debug") === "1";

  if (!isDebugEnabled) {
    return null;
  }

  const info = getTelegramDebugInfo();
  const isDev = import.meta.env.DEV;
  const mask = (v: string | number | undefined | null) =>
    isDev ? v : "***";

  return (
    <div className="mt-4 w-full rounded-lg border border-slate-700 bg-slate-900 p-3 text-left text-xs text-slate-400">
      <p className="mb-2 font-semibold text-slate-300">
        Telegram Debug {!isDev && "(production — PII masked)"}
      </p>
      <table className="w-full">
        <tbody>
          <tr>
            <td className="pr-2 text-slate-500">isTelegramWebApp</td>
            <td className={info.isTelegramWebApp ? "text-green-400" : "text-rose-400"}>
              {String(info.isTelegramWebApp)}
            </td>
          </tr>
          <tr>
            <td className="pr-2 text-slate-500">initData length</td>
            <td>{info.initDataLength}</td>
          </tr>
          <tr>
            <td className="pr-2 text-slate-500">initDataUnsafe keys</td>
            <td>{info.initDataUnsafeKeys}</td>
          </tr>
          <tr>
            <td className="pr-2 text-slate-500">user id</td>
            <td>{mask(info.userId)}</td>
          </tr>
          <tr>
            <td className="pr-2 text-slate-500">auth_date</td>
            <td>{mask(info.authDate)}</td>
          </tr>
          <tr>
            <td className="pr-2 text-slate-500">query_id</td>
            <td>{mask(info.queryId)}</td>
          </tr>
          <tr>
            <td className="pr-2 text-slate-500">platform</td>
            <td>{info.platform}</td>
          </tr>
          <tr>
            <td className="pr-2 text-slate-500">version</td>
            <td>{info.version}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
};

export default TelegramDebugPanel;
