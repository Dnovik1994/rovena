import React, { useState } from "react";

import { apiFetch, API_PATHS, ApiError } from "../shared/api/client";
import { useAuth } from "../stores/auth";
import { parseJwtExpiry } from "../utils/authStorage";
import { diagnoseInitData, getTelegramWebApp, isTelegramWebApp } from "../utils/telegram";
import TelegramDebugPanel from "../components/TelegramDebugPanel";

const Login = (): JSX.Element => {
  const { setToken, setOnboardingNeeded } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const hasDevInitData = import.meta.env.DEV && Boolean(import.meta.env.VITE_TG_INIT_DATA);

  const handleLogin = async () => {
    setLoading(true);
    setError(null);
    try {
      const webapp = getTelegramWebApp();
      if (import.meta.env.DEV) {
        const initDataLength = webapp?.initData?.length ?? 0;
        // eslint-disable-next-line no-console
        console.log("Telegram initData length:", initDataLength, "non_empty:", initDataLength > 0);
      }
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
      }>(API_PATHS.telegramAuth, {
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
      const apiError = err as ApiError;
      const statusInfo = apiError.status ? `Статус: ${apiError.status}. ` : "";
      const bodyInfo = apiError.body ? `Ответ: ${apiError.body}` : "";
      const details = `${statusInfo}${bodyInfo}`.trim();
      setError(`Не удалось войти через Telegram.${details ? ` ${details}` : ""}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <section className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center gap-4 px-4 text-center">
        <h1 className="text-3xl font-semibold">FreeCRM Inviter</h1>
        <p className="page__subtitle">
          Авторизуйтесь через Telegram WebApp, чтобы продолжить.
        </p>

        {!isTelegramWebApp() && !hasDevInitData && (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-300">
            Telegram WebApp не обнаружен. Откройте это приложение через
            Telegram-бот (кнопка Menu или Inline Button).
          </div>
        )}

        <button
          onClick={handleLogin}
          className="btn btn--primary"
          disabled={loading}
        >
          {loading ? "Подключаем..." : "Войти"}
        </button>
        {error && <p className="hint">{error}</p>}

        <TelegramDebugPanel />
      </section>
    </div>
  );
};

export default Login;
