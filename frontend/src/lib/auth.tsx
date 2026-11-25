"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useSyncExternalStore, type ReactNode } from "react";

import { api, setUnauthorizedHandler, tokenStore } from "./api";
import type { User } from "./types";

interface AuthContextValue {
  user: User | null;
  ready: boolean;
  login: (username: string, password: string) => Promise<User>;
  logout: () => void;
  can: (permission: string) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

// Session state lives in sessionStorage; React reads it through an external-store
// subscription so server rendering (no user) and client hydration stay consistent.
const listeners = new Set<() => void>();
let cachedRaw: string | null | undefined;
let cachedUser: User | null = null;

function readUser(): User | null {
  const raw = typeof window === "undefined" ? null : window.sessionStorage.getItem("agentguard.user");
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    cachedUser = raw ? (JSON.parse(raw) as User) : null;
  }
  return cachedUser;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

function notify() {
  listeners.forEach((listener) => listener());
}

const subscribeNoop = () => () => {};

export function AuthProvider({ children }: { children: ReactNode }) {
  const user = useSyncExternalStore(subscribe, readUser, () => null);
  const hydrated = useSyncExternalStore(subscribeNoop, () => true, () => false);
  const router = useRouter();

  const logout = useCallback(() => {
    tokenStore.clear();
    notify();
    router.replace("/login");
  }, [router]);

  useEffect(() => {
    setUnauthorizedHandler(logout);
  }, [logout]);

  useEffect(() => {
    // Re-validate a restored session in the background; a stale token logs the user out.
    if (!hydrated || !user || !tokenStore.get()) return;
    api
      .me()
      .then((fresh) => {
        tokenStore.set(tokenStore.get() ?? "", fresh);
        notify();
      })
      .catch(() => undefined);
    // Only on first hydration with a stored user.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hydrated]);

  const login = useCallback(async (username: string, password: string) => {
    const response = await api.login(username, password);
    tokenStore.set(response.access_token, response.user);
    notify();
    return response.user;
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      ready: hydrated,
      login,
      logout,
      can: (permission: string) => Boolean(user?.permissions.includes(permission)),
    }),
    [user, hydrated, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

/** Redirects to /login when there is no session. Returns true once the user is known. */
export function useRequireAuth(): boolean {
  const { user, ready } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  useEffect(() => {
    if (ready && !user && pathname !== "/login") router.replace("/login");
  }, [ready, user, pathname, router]);
  return ready && Boolean(user);
}
