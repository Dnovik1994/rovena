import React, { useEffect } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import AppShell from "./components/AppShell";
import Accounts from "./pages/Accounts";
import Admin from "./pages/Admin";
import Campaigns from "./pages/Campaigns";
import Contacts from "./pages/Contacts";
import Dashboard from "./pages/Dashboard";
import ErrorPage from "./pages/ErrorPage";
import Login from "./pages/Login";
import Projects from "./pages/Projects";
import Sources from "./pages/Sources";
import Subscription from "./pages/Subscription";
import Targets from "./pages/Targets";
import { apiFetch } from "./services/api";
import { AuthProvider, useAuth } from "./stores/auth";
import { UserProfile } from "./types/user";
import { applyTelegramTheme } from "./utils/telegramTheme";

const AppRoutes = (): JSX.Element => {
  const { token, user, setUser } = useAuth();

  useEffect(() => {
    if (!token) {
      setUser(null);
      return;
    }
    apiFetch<UserProfile>("/me", {}, token)
      .then((data) => setUser(data))
      .catch(() => setUser(null));
  }, [token, setUser]);

  if (!token) {
    return <Login />;
  }

  return (
    <AppShell isAdmin={user?.is_admin ?? false}>
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
        <Route path="/error/:code" element={<ErrorPage />} />
      </Routes>
    </AppShell>
  );
};

const App = (): JSX.Element => {
  useEffect(() => {
    const telegram = (window as unknown as { Telegram?: { WebApp?: { onEvent?: (event: string, handler: () => void) => void; offEvent?: (event: string, handler: () => void) => void; themeParams?: Record<string, string> } } }).Telegram
      ?.WebApp;

    if (!telegram?.onEvent) {
      return;
    }

    const updateTheme = () => applyTelegramTheme(telegram.themeParams);

    telegram.onEvent("themeChanged", updateTheme);
    return () => {
      telegram.offEvent?.("themeChanged", updateTheme);
    };
  }, []);

  return (
    <AuthProvider>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </AuthProvider>
  );
};

export default App;
