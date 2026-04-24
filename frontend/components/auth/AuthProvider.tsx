"use client";

/**
 * Client-side auth context. Loads the current user from /api/auth/me on
 * mount, exposes login/signup/logout actions, and tracks a loading state
 * so protected pages can render a spinner instead of flashing the login
 * page while we check.
 */

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import {
  AuthUser,
  fetchMe,
  login as apiLogin,
  logout as apiLogout,
  signup as apiSignup,
} from "@/lib/auth";

type Status = "loading" | "anonymous" | "authenticated";

interface AuthContextValue {
  status: Status;
  user: AuthUser | null;
  login: (email: string, password: string) => Promise<void>;
  signup: (params: {
    email: string;
    password: string;
    display_name?: string;
    organization_name?: string;
  }) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [status, setStatus] = useState<Status>("loading");

  const refresh = useCallback(async () => {
    const me = await fetchMe();
    setUser(me);
    setStatus(me ? "authenticated" : "anonymous");
  }, []);

  useEffect(() => {
    refresh().catch(() => {
      setUser(null);
      setStatus("anonymous");
    });
  }, [refresh]);

  const login = useCallback(async (email: string, password: string) => {
    const u = await apiLogin(email, password);
    setUser(u);
    setStatus("authenticated");
  }, []);

  const signup = useCallback(
    async (params: {
      email: string;
      password: string;
      display_name?: string;
      organization_name?: string;
    }) => {
      const u = await apiSignup(params);
      setUser(u);
      setStatus("authenticated");
    },
    [],
  );

  const logout = useCallback(async () => {
    await apiLogout();
    setUser(null);
    setStatus("anonymous");
  }, []);

  return (
    <AuthContext.Provider value={{ status, user, login, signup, logout, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within <AuthProvider>");
  return ctx;
}
