import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { get, post, setUnauthorizedHandler, tokens } from "./api";
import type { Me } from "../types";

interface AuthState {
  me: Me | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<Me>;
  logout: () => Promise<void>;
  can: (perm: string) => boolean;
}

const Ctx = createContext<AuthState>(null as unknown as AuthState);
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(!!tokens.access);

  useEffect(() => {
    setUnauthorizedHandler(() => setMe(null));
    if (!tokens.access) return;
    get<Me>("/auth/me/").then(setMe).catch(() => tokens.clear()).finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const d = await post<{ access: string; refresh: string; user: Me }>("/auth/login/", { email, password });
    tokens.set(d.access, d.refresh);
    setMe(d.user);
    return d.user;
  }, []);

  const logout = useCallback(async () => {
    try { await post("/auth/logout/", { refresh: tokens.refresh }); } catch { /* déconnexion locale quoi qu'il arrive */ }
    tokens.clear();
    setMe(null);
  }, []);

  const value = useMemo<AuthState>(() => ({
    me, loading, login, logout,
    can: (perm) => !!me?.permissions.includes(perm),
  }), [me, loading, login, logout]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
