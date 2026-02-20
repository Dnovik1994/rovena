import React, { type ReactElement } from "react";
import { render, type RenderOptions, type RenderResult } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "../stores/auth";

interface ProviderOptions {
  /** Initial route for MemoryRouter (default: "/") */
  route?: string;
  /** Pre-configured QueryClient (default: fresh client with retry: false) */
  queryClient?: QueryClient;
}

function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

/**
 * Renders a component wrapped in the same provider hierarchy as the real app:
 * QueryClientProvider → AuthProvider → MemoryRouter
 */
export function renderWithProviders(
  ui: ReactElement,
  options: ProviderOptions & Omit<RenderOptions, "wrapper"> = {},
): RenderResult {
  const { route = "/", queryClient, ...renderOptions } = options;
  const testClient = queryClient ?? createTestQueryClient();

  function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={testClient}>
        <AuthProvider>
          <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
        </AuthProvider>
      </QueryClientProvider>
    );
  }

  return render(ui, { wrapper: Wrapper, ...renderOptions });
}

export { createTestQueryClient };
