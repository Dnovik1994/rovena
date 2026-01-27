import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { UserProfile } from "../types/user";
import {
  clearStoredTokens,
  getStoredTokens,
  onTokensChanged,
  setStoredTokens,
} from "../utils/authStorage";

interface AuthContextValue {
  token: string | null;
  refreshToken: string | null;
  user: UserProfile | null;
  setToken: (token: string | null, refreshToken?: string | null, expiresAt?: number | null) => void;
  onboardingNeeded: boolean;
  setOnboardingNeeded: (value: boolean) => void;
  logout: () => void;
  setUser: (user: UserProfile | null) => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export const AuthProvider = ({ children }: { children: React.ReactNode }): JSX.Element => {
  const [token, setTokenState] = useState<string | null>(null);
  const [refreshToken, setRefreshTokenState] = useState<string | null>(null);
  const [user, setUserState] = useState<UserProfile | null>(null);
  const [onboardingNeeded, setOnboardingNeededState] = useState(false);

  useEffect(() => {
    const syncTokens = () => {
      const stored = getStoredTokens();
      setTokenState(stored.accessToken);
      setRefreshTokenState(stored.refreshToken);
    };
    syncTokens();
    return onTokensChanged(syncTokens);
  }, []);

  const setToken = useCallback(
    (value: string | null, refreshValue?: string | null, expiresAt?: number | null) => {
    setTokenState(value);
    if (typeof refreshValue !== "undefined") {
      setRefreshTokenState(refreshValue);
    }
    setStoredTokens({
      accessToken: value,
      refreshToken: typeof refreshValue === "undefined" ? refreshToken : refreshValue,
      accessTokenExpiresAt: typeof expiresAt === "undefined" ? null : expiresAt,
    });
  }, [refreshToken]);

  const setUser = useCallback((value: UserProfile | null) => {
    setUserState(value);
  }, []);

  const setOnboardingNeeded = useCallback((value: boolean) => {
    setOnboardingNeededState(value);
  }, []);

  const logout = useCallback(() => {
    setTokenState(null);
    setRefreshTokenState(null);
    setUserState(null);
    setOnboardingNeededState(false);
    clearStoredTokens();
  }, []);

  const value = useMemo(
    () => ({
      token,
      refreshToken,
      user,
      setToken,
      setUser,
      onboardingNeeded,
      setOnboardingNeeded,
      logout,
    }),
    [token, refreshToken, user, setToken, setUser, onboardingNeeded, setOnboardingNeeded, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = (): AuthContextValue => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
};
