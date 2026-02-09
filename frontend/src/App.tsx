import React, { Suspense, useEffect, lazy } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";

import AppShell from "./components/AppShell";
import ErrorBoundary from "./components/ErrorBoundary";
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
import { apiFetch } from "./services/api";
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

  useEffect(() => {
    if (!token) {
      setUser(null);
      setOnboardingNeeded(false);
      return;
    }
    apiFetch<UserProfile>("/me", {}, token)
      .then((data) => {
        setUser(data);
        setOnboardingNeeded(!data.onboarding_completed);
      })
      .catch(() => {
        setUser(null);
        setOnboardingNeeded(false);
      });
  }, [token, setOnboardingNeeded, setUser]);

  if (token && onboardingNeeded && location.pathname !== "/onboarding") {
    return <Navigate to="/onboarding" replace />;
  }

  if (!token) {
    return <Login />;
  }

  return (
    <AppShell isAdmin={user?.is_admin ?? false}>
      <Suspense fallback={<div className="rounded-2xl bg-slate-900/60 p-4 text-sm text-slate-300">Загрузка...</div>}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/accounts" element={<Accounts />} />
          <Route path="/projects" element={<Projects />} />
          <Route path="/sources" element={<Sources />} />
          <Route path="/targets" element={<Targets />} />
          <Route path="/contacts" element={<Contacts />} />
          <Route path="/campaigns" element={<Campaigns />} />
          <Route path="/subscription" element={<Subscription />} />
          <Route path="/admin" element={<Admin />} />
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

    telegram.onEvent("themeChanged", updateTheme);
    return () => {
      telegram.offEvent("themeChanged", updateTheme);
    };
  }, []);

  return (
    <ErrorBoundary>
      <AuthProvider>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </AuthProvider>
    </ErrorBoundary>
  );
};

export default App;
