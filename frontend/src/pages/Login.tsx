import React, { useState } from "react";

import { apiFetch } from "../services/api";
import { useAuth } from "../stores/auth";
import { parseJwtExpiry } from "../utils/authStorage";
import { diagnoseInitData, isTelegramWebApp } from "../utils/telegram";
import TelegramDebugPanel from "../components/TelegramDebugPanel";

const Login = (): JSX.Element => {
  const { setToken, setOnboardingNeeded } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleLogin = async () => {
    setLoading(true);
    setError(null);
    try {
      const status = diagnoseInitData();

      if (status.kind === "no_telegram") {
        setError(
          "Откройте приложение внутри Telegram (через кнопку WebApp/Menu), в браузере initData нет."
        );
        return;
      }

      if (status.kind === "empty_init_data") {
        setError(
          "Telegram WebApp обнаружен, но initData пуст. " +
            "Возможные причины: приложение открыто не через кнопку бота (Menu Button / Inline Button), " +
            "или ссылка открыта напрямую в браузере Telegram без запуска Mini App."
        );
        return;
      }

      const response = await apiFetch<{
        access_token: string;
        refresh_token: string;
        onboarding_needed?: boolean;
      }>("/auth/telegram", {
        method: "POST",
        body: JSON.stringify({ init_data: status.initData }),
      });
      setToken(
        response.access_token,
        response.refresh_token,
        parseJwtExpiry(response.access_token)
      );
      setOnboardingNeeded(Boolean(response.onboarding_needed));
    } catch (err) {
      setError("Не удалось войти через Telegram.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <section className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center gap-4 px-4 text-center">
        <h1 className="text-3xl font-semibold">FreeCRM Inviter</h1>
        <p className="text-sm text-slate-400">
          Авторизуйтесь через Telegram WebApp, чтобы продолжить.
        </p>

        {!isTelegramWebApp() && !import.meta.env.VITE_TG_INIT_DATA && (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-300">
            Telegram WebApp не обнаружен. Откройте это приложение через
            Telegram-бот (кнопка Menu или Inline Button).
          </div>
        )}

        <button
          onClick={handleLogin}
          className="rounded-xl bg-indigo-500 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
          disabled={loading}
        >
          {loading ? "Подключаем..." : "Войти"}
        </button>
        {error && <p className="text-sm text-rose-400">{error}</p>}

        <TelegramDebugPanel />
      </section>
    </div>
  );
};

export default Login;
