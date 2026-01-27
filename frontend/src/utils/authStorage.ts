const ACCESS_TOKEN_KEY = "access_token";
const REFRESH_TOKEN_KEY = "refresh_token";
const ACCESS_EXPIRES_AT_KEY = "access_token_expires_at";
const TOKENS_EVENT = "auth:tokens";

export interface StoredTokens {
  accessToken: string | null;
  refreshToken: string | null;
  accessTokenExpiresAt: number | null;
}

const getStorage = (): Storage | null => {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage;
};

export const parseJwtExpiry = (token: string): number | null => {
  try {
    const payload = token.split(".")[1];
    const decoded = JSON.parse(atob(payload));
    if (typeof decoded.exp === "number") {
      return decoded.exp * 1000;
    }
  } catch {
    return null;
  }
  return null;
};

export const getStoredTokens = (): StoredTokens => {
  const storage = getStorage();
  if (!storage) {
    return { accessToken: null, refreshToken: null, accessTokenExpiresAt: null };
  }
  const accessToken = storage.getItem(ACCESS_TOKEN_KEY);
  const refreshToken = storage.getItem(REFRESH_TOKEN_KEY);
  const expiresRaw = storage.getItem(ACCESS_EXPIRES_AT_KEY);
  const accessTokenExpiresAt = expiresRaw ? Number(expiresRaw) : null;
  return { accessToken, refreshToken, accessTokenExpiresAt };
};

export const setStoredTokens = (tokens: StoredTokens): void => {
  const storage = getStorage();
  if (!storage) {
    return;
  }
  if (tokens.accessToken) {
    storage.setItem(ACCESS_TOKEN_KEY, tokens.accessToken);
  } else {
    storage.removeItem(ACCESS_TOKEN_KEY);
  }
  if (tokens.refreshToken) {
    storage.setItem(REFRESH_TOKEN_KEY, tokens.refreshToken);
  } else {
    storage.removeItem(REFRESH_TOKEN_KEY);
  }
  if (tokens.accessTokenExpiresAt) {
    storage.setItem(ACCESS_EXPIRES_AT_KEY, String(tokens.accessTokenExpiresAt));
  } else {
    storage.removeItem(ACCESS_EXPIRES_AT_KEY);
  }
  window.dispatchEvent(new Event(TOKENS_EVENT));
};

export const clearStoredTokens = (): void => {
  setStoredTokens({ accessToken: null, refreshToken: null, accessTokenExpiresAt: null });
};

export const onTokensChanged = (handler: () => void): (() => void) => {
  const listener = () => handler();
  window.addEventListener(TOKENS_EVENT, listener);
  return () => window.removeEventListener(TOKENS_EVENT, listener);
};
