import React, { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

import Toast from "./Toast";
const navItems = [
  { to: "/", label: "Dashboard" },
  { to: "/accounts", label: "Accounts" },
  { to: "/projects", label: "Projects" },
  { to: "/sources", label: "Sources" },
  { to: "/targets", label: "Targets" },
  { to: "/contacts", label: "Contacts" },
  { to: "/campaigns", label: "Campaigns" },
  { to: "/invite-campaigns", label: "Inviter" },
  { to: "/subscription", label: "Subscription" },
];

interface AppShellProps {
  children: React.ReactNode;
  isAdmin?: boolean;
}

const AppShell = ({ children, isAdmin = false }: AppShellProps): JSX.Element => {
  const [isOnline, setIsOnline] = useState(() => navigator.onLine);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  useEffect(() => {
    const handleOnline = () => setIsOnline(true);
    const handleOffline = () => setIsOnline(false);
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<{ message?: string }>).detail;
      if (!detail?.message) {
        return;
      }
      setToastMessage(detail.message);
      window.setTimeout(() => setToastMessage(null), 3000);
    };
    window.addEventListener("app:toast", handler as EventListener);
    return () => {
      window.removeEventListener("app:toast", handler as EventListener);
    };
  }, []);

  return (
    <div className="app-shell">
      {toastMessage && <Toast message={toastMessage} />}
      <header className="app-shell__container" style={{ paddingBottom: 0 }}>
        <div className="page__header" style={{ alignItems: "center" }}>
          <div>
            <p className="label" style={{ marginBottom: 0 }}>
              FreeCRM Inviter
            </p>
            <h1 className="page__title" style={{ fontSize: "1.2rem" }}>Mini App</h1>
          </div>
          {isAdmin && (
            <NavLink
              to="/admin"
              className="btn btn--ghost"
            >
              Admin Panel
            </NavLink>
          )}
        </div>
        {!isOnline && (
          <div className="error" style={{ marginTop: "8px", padding: "10px" }}>
            Offline mode: некоторые данные могут быть недоступны.
          </div>
        )}
        <nav className="nav" style={{ marginTop: "12px" }}>
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                ["nav__item", isActive ? "nav__item--active" : ""].join(" ").trim()
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="app-shell__container app-main">{children}</main>
    </div>
  );
};

export default AppShell;
