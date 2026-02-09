import React from "react";
import { getTelegramDebugInfo } from "../utils/telegram";

const TelegramDebugPanel = (): JSX.Element | null => {
  if (!import.meta.env.DEV) {
    return null;
  }

  const info = getTelegramDebugInfo();

  return (
    <div className="mt-4 w-full rounded-lg border border-slate-700 bg-slate-900 p-3 text-left text-xs text-slate-400">
      <p className="mb-2 font-semibold text-slate-300">Telegram Debug</p>
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
