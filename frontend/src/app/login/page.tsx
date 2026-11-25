"use client";

import { Activity } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { ErrorBanner } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { roleLabel } from "@/lib/format";
import type { DemoUsers } from "@/lib/types";

export default function LoginPage() {
  const { login, user, ready } = useAuth();
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [demo, setDemo] = useState<DemoUsers | null>(null);

  useEffect(() => {
    if (ready && user) router.replace("/");
  }, [ready, user, router]);

  useEffect(() => {
    api.demoUsers().then(setDemo).catch(() => setDemo(null));
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username.trim(), password);
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="mb-8 flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-accent-soft text-accent">
            <Activity className="h-6 w-6" />
          </div>
          <div>
            <h1 className="text-xl font-semibold tracking-tight">AgentGuard</h1>
            <p className="text-xs text-muted">AI agent reliability &amp; security platform · The GenAI Foundry</p>
          </div>
        </div>
        <form onSubmit={onSubmit} className="space-y-4 rounded-lg border border-border bg-surface p-6">
          <div>
            <Label htmlFor="username">Username</Label>
            <Input id="username" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
          </div>
          <div>
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>
          <ErrorBanner message={error} />
          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </Button>
        </form>
        {demo?.enabled ? (
          <div className="mt-4 rounded-lg border border-border bg-surface p-4 text-xs text-muted">
            <p className="mb-2 font-medium text-foreground">Demo accounts (local development only)</p>
            <ul className="grid grid-cols-2 gap-1.5">
              {demo.users.map((u) => (
                <li key={u.username}>
                  <button
                    type="button"
                    className="w-full rounded border border-border px-2 py-1.5 text-left hover:border-accent hover:text-foreground"
                    onClick={() => {
                      setUsername(u.username);
                      setPassword(demo.password ?? "");
                    }}
                  >
                    <div className="font-mono text-[11px] text-accent">{u.username}</div>
                    <div>{roleLabel(u.role)}</div>
                  </button>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-[11px] text-subtle">
              Click an account to fill the form. Password: <span className="font-mono">{demo.password}</span>
            </p>
          </div>
        ) : null}
        <p className="mt-6 text-center text-[11px] text-subtle">
          Everything here is a simulation with fictional data. No real payments are ever made.
        </p>
      </div>
    </div>
  );
}
