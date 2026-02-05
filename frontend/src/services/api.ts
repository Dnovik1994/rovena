import {
  clearStoredTokens,
  getStoredTokens,
  parseJwtExpiry,
  setStoredTokens,
} from "../utils/authStorage";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api/v1";

/** Default request timeout in milliseconds. */
const DEFAULT_TIMEOUT_MS = 15_000;
/** Timeout for token-refresh requests (shorter, should be fast). */
const REFRESH_TIMEOUT_MS = 10_000;

export interface ApiError {
  code: string;
  message: string;
}

export const parseApiError = async (response: Response): Promise<ApiError> => {
  try {
    const data = (await response.json()) as { error?: ApiError };
    if (data.error) {
      return data.error;
    }
  } catch {
    return { code: String(response.status), message: "Unexpected error" };
  }
  return { code: String(response.status), message: response.statusText };
};

/**
 * Perform an API request with automatic timeout, token injection,
 * and 401-refresh retry.
 *
 * @param timeoutMs — override the default 15 s timeout per call.
 */
export const apiFetch = async <T>(
  path: string,
  options: RequestInit = {},
  token?: string | null,
  retryOnUnauthorized = true,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<T> => {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  const stored = getStoredTokens();
  const authToken = token ?? stored.accessToken;
  if (authToken) {
    headers.set("Authorization", `Bearer ${authToken}`);
  }

  // AbortController: timeout + caller-provided signal support.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  // If the caller already provided a signal, chain it.
  if (options.signal) {
    options.signal.addEventListener("abort", () => controller.abort(), { once: true });
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers,
      signal: controller.signal,
    });
  } catch (err: unknown) {
    clearTimeout(timer);
    if (err instanceof DOMException && err.name === "AbortError") {
      throw { code: "TIMEOUT", message: "Запрос не отвечает. Проверьте соединение." } as ApiError;
    }
    throw { code: "NETWORK", message: "Ошибка сети. Проверьте подключение." } as ApiError;
  } finally {
    clearTimeout(timer);
  }

  if (response.status === 401 && retryOnUnauthorized && !path.includes("/auth/refresh")) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      return apiFetch<T>(path, options, refreshed, false, timeoutMs);
    }
  }

  if (response.status === 403) {
    clearStoredTokens();
    if (window.location.pathname !== "/") {
      window.location.href = "/";
    }
  }

  if (response.status === 429) {
    window.dispatchEvent(new CustomEvent("app:toast", { detail: { message: "Rate limit exceeded" } }));
  }

  if (response.status >= 500) {
    if (!window.location.pathname.startsWith("/error")) {
      window.location.href = `/error/${response.status}`;
    }
  }

  if (!response.ok) {
    throw await parseApiError(response);
  }

  return (await response.json()) as T;
};

export const refreshAccessToken = async (): Promise<string | null> => {
  const { refreshToken } = getStoredTokens();
  if (!refreshToken) {
    return null;
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REFRESH_TIMEOUT_MS);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
      signal: controller.signal,
    });
  } catch {
    clearTimeout(timer);
    clearStoredTokens();
    return null;
  } finally {
    clearTimeout(timer);
  }

  if (!response.ok) {
    clearStoredTokens();
    return null;
  }
  const data = (await response.json()) as { access_token: string; refresh_token?: string };
  const nextRefresh = data.refresh_token ?? refreshToken;
  setStoredTokens({
    accessToken: data.access_token,
    refreshToken: nextRefresh,
    accessTokenExpiresAt: parseJwtExpiry(data.access_token),
  });
  return data.access_token;
};
