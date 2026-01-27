import React, { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

const navItems = [
  { to: "/", label: "Dashboard" },
  { to: "/accounts", label: "Accounts" },
  { to: "/projects", label: "Projects" },
  { to: "/sources", label: "Sources" },
  { to: "/targets", label: "Targets" },
  { to: "/contacts", label: "Contacts" },
  { to: "/campaigns", label: "Campaigns" },
  { to: "/subscription", label: "Subscription" },
];

interface AppShellProps {
  children: React.ReactNode;
  isAdmin?: boolean;
}

const AppShell = ({ children, isAdmin = false }: AppShellProps): JSX.Element => {
  const [isOnline, setIsOnline] = useState(() => navigator.onLine);

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

  return (
    <div className="min-h-screen bg-[var(--tg-theme-bg)] text-[var(--tg-theme-text)]">
      <header className="border-b border-slate-800/60">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-4">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-[var(--tg-theme-hint)]">
              FreeCRM Inviter
            </p>
            <h1 className="text-lg font-semibold">Mini App</h1>
          </div>
          {isAdmin && (
            <NavLink
              to="/admin"
              className="rounded-full border border-[var(--tg-theme-link)] px-3 py-1 text-xs text-[var(--tg-theme-link)]"
            >
              Admin Panel
            </NavLink>
          )}
        </div>
        {!isOnline && (
          <div className="bg-rose-500/10 px-4 py-2 text-center text-xs text-rose-200">
            Offline mode: некоторые данные могут быть недоступны.
          </div>
        )}
        <nav className="mx-auto flex max-w-5xl gap-2 overflow-x-auto px-4 pb-4">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                [
                  "rounded-full px-3 py-1 text-sm",
                  isActive
                    ? "bg-[var(--tg-theme-button)] text-[var(--tg-theme-button-text)]"
                    : "bg-[var(--tg-theme-secondary-bg)] text-[var(--tg-theme-hint)]",
                ].join(" ")
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
    </div>
  );
};

export default AppShell;
