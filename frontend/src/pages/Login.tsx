import React, { useState } from "react";

import { apiFetch } from "../services/api";
import { useAuth } from "../stores/auth";
import { parseJwtExpiry } from "../utils/authStorage";

const Login = (): JSX.Element => {
  const { setToken, setOnboardingNeeded } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const getInitData = (): string => {
    const tg = (window as typeof window & { Telegram?: any }).Telegram;
    if (tg?.WebApp?.initData) {
      return tg.WebApp.initData;
    }
    return import.meta.env.VITE_TG_INIT_DATA || "";
  };

  const handleLogin = async () => {
    setLoading(true);
    setError(null);
    try {
      const initData = getInitData();
      if (!initData) {
        setError("Нет initData. Укажите VITE_TG_INIT_DATA для локального запуска.");
        return;
      }
      const response = await apiFetch<{
        access_token: string;
        refresh_token: string;
        onboarding_needed?: boolean;
      }>(
        "/auth/telegram",
        {
          method: "POST",
          body: JSON.stringify({ init_data: initData }),
        }
      );
      setToken(response.access_token, response.refresh_token, parseJwtExpiry(response.access_token));
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
        <button
          onClick={handleLogin}
          className="rounded-xl bg-indigo-500 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
          disabled={loading}
        >
          {loading ? "Подключаем..." : "Войти"}
        </button>
        {error && <p className="text-sm text-rose-400">{error}</p>}
      </section>
    </div>
  );
};

export default Login;
