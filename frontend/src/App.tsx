import React, { Suspense, useEffect, lazy } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";

import AppShell from "./components/AppShell";
import ErrorBoundary from "./components/ErrorBoundary";
import TelegramWebAppGuard from "./components/TelegramWebAppGuard";
import Accounts from "./pages/Accounts";
import Campaigns from "./pages/Campaigns";
import Contacts from "./pages/Contacts";
import Dashboard from "./pages/Dashboard";
import ErrorPage from "./pages/ErrorPage";
import Login from "./pages/Login";
import Onboarding from "./pages/Onboarding";
import Projects from "./pages/Projects";
import Sources from "./pages/Sources";
import Targets from "./pages/Targets";
import AccountChats from "./pages/AccountChats";
import AccountDialogs from "./pages/AccountDialogs";
import InviteCampaigns from "./pages/InviteCampaigns";
import { apiFetch } from "./shared/api/client";
import { AuthProvider, useAuth } from "./stores/auth";
import { UserProfile } from "./types/user";
import { getTelegramWebApp } from "./utils/telegram";
import { applyTelegramTheme } from "./utils/telegramTheme";

const Admin = lazy(() => import("./pages/Admin"));
const NotFound = lazy(() => import("./pages/NotFound"));
const Subscription = lazy(() => import("./pages/Subscription"));

const AppRoutes = (): JSX.Element => {
  const { token, user, setUser, onboardingNeeded, setOnboardingNeeded } = useAuth();
  const location = useLocation();
  const [profileError, setProfileError] = React.useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      setUser(null);
      setOnboardingNeeded(false);
      setProfileError(null);
      return;
    }
    setProfileError(null);
    apiFetch<UserProfile>("/me", {}, token)
      .then((data) => {
        setUser(data);
        setOnboardingNeeded(!data.onboarding_completed);
      })
      .catch((err) => {
        const status = err?.status ?? err?.code ?? "unknown";
        const message = err?.message ?? "unknown error";
        console.error("[/me] failed to load profile", { status, message });
        // Keep token — do not silently discard the session.
        // Show degraded state instead so the user knows something is wrong.
        setUser(null);
        setOnboardingNeeded(false);
        setProfileError(`Не удалось загрузить профиль (${status})`);
      });
  }, [token, setOnboardingNeeded, setUser]);

  if (token && profileError) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-950 p-4">
        <div className="rounded-2xl bg-red-900/40 border border-red-700 p-6 text-center text-sm text-red-200 max-w-md">
          <p className="font-semibold mb-2">Ошибка загрузки профиля</p>
          <p>{profileError}</p>
          <p className="mt-3 text-xs text-red-300">Попробуйте обновить страницу. Если проблема сохраняется — обратитесь в поддержку.</p>
        </div>
      </div>
    );
  }

  if (token && onboardingNeeded && location.pathname !== "/onboarding") {
    return <Navigate to="/onboarding" replace />;
  }

  if (!token) {
    return <Login />;
  }

  const isAdmin = user?.role === "admin" || user?.role === "superadmin";

  return (
    <AppShell isAdmin={isAdmin}>
      <Suspense fallback={<div className="rounded-2xl bg-slate-900/60 p-4 text-sm text-slate-300">Загрузка...</div>}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/accounts" element={<Accounts />} />
          <Route path="/projects" element={<Projects />} />
          <Route path="/sources" element={<Sources />} />
          <Route path="/targets" element={<Targets />} />
          <Route path="/contacts" element={<Contacts />} />
          <Route path="/campaigns" element={<Campaigns />} />
          <Route path="/accounts/:accountId/chats" element={<AccountChats />} />
          <Route path="/accounts/:accountId/dialogs" element={<AccountDialogs />} />
          <Route path="/invite-campaigns" element={<InviteCampaigns />} />
          <Route path="/subscription" element={<Subscription />} />
          <Route path="/admin" element={isAdmin ? <Admin /> : <Navigate to="/" replace />} />
          <Route path="/onboarding" element={<Onboarding />} />
          <Route path="/error/:code" element={<ErrorPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Suspense>
    </AppShell>
  );
};

const App = (): JSX.Element => {
  useEffect(() => {
    const telegram = getTelegramWebApp();
    if (!telegram) {
      return;
    }

    const updateTheme = () => applyTelegramTheme(telegram.themeParams);

    telegram.ready();
    telegram.expand?.();
    updateTheme();
    telegram.onEvent("themeChanged", updateTheme);
    return () => {
      telegram.offEvent("themeChanged", updateTheme);
    };
  }, []);

  return (
    <ErrorBoundary>
      <AuthProvider>
        <TelegramWebAppGuard>
          <BrowserRouter>
            <AppRoutes />
          </BrowserRouter>
        </TelegramWebAppGuard>
      </AuthProvider>
    </ErrorBoundary>
  );
};

export default App;
