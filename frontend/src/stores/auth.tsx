import React, { createContext, useCallback, useContext, useMemo, useState } from "react";

import { UserProfile } from "../types/user";

interface AuthContextValue {
  token: string | null;
  user: UserProfile | null;
  setToken: (token: string | null) => void;
  setUser: (user: UserProfile | null) => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export const AuthProvider = ({ children }: { children: React.ReactNode }): JSX.Element => {
  const [token, setTokenState] = useState<string | null>(null);
  const [user, setUserState] = useState<UserProfile | null>(null);

  const setToken = useCallback((value: string | null) => {
    setTokenState(value);
  }, []);

  const setUser = useCallback((value: UserProfile | null) => {
    setUserState(value);
  }, []);

  const value = useMemo(() => ({ token, user, setToken, setUser }), [token, user, setToken, setUser]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = (): AuthContextValue => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
};
