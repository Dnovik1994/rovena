import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import App from "./App";
import "./styles/index.css";
import { applyTelegramTheme } from "./utils/telegramTheme";

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("Root element #root not found");
}

const queryClient = new QueryClient();

const telegram = (window as unknown as { Telegram?: { WebApp?: { ready?: () => void; themeParams?: Record<string, string> } } }).Telegram
  ?.WebApp;
if (telegram) {
  telegram.ready?.();
  applyTelegramTheme(telegram.themeParams);
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>
);
