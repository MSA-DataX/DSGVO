"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { RequireAdmin } from "@/components/auth/RequireAdmin";
import { UserMenu } from "@/components/auth/UserMenu";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { useAuth } from "@/components/auth/AuthProvider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useLang } from "@/lib/LanguageContext";
import {
  AdminError,
  demoteUser,
  listAudit,
  listOrganizations,
  listUsers,
  promoteUser,
  resetPassword,
} from "@/lib/admin";
import type {
  AdminAuditEntry,
  AdminOrganization,
  AdminUser,
} from "@/lib/types";

export default function AdminPage() {
  return (
    <RequireAdmin>
      <AdminDashboard />
    </RequireAdmin>
  );
}

function AdminDashboard() {
  const { t } = useLang();

  return (
    <main className="container mx-auto max-w-6xl py-8">
      <header className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold">{t("admin.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("admin.subtitle")}</p>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/" className="text-sm text-muted-foreground hover:underline">
            ← {t("admin.backToDashboard")}
          </Link>
          <LanguageSwitcher />
          <UserMenu />
        </div>
      </header>

      <Tabs defaultValue="users">
        <TabsList>
          <TabsTrigger value="users">{t("admin.tab.users")}</TabsTrigger>
          <TabsTrigger value="organizations">{t("admin.tab.organizations")}</TabsTrigger>
          <TabsTrigger value="audit">{t("admin.tab.audit")}</TabsTrigger>
        </TabsList>

        <TabsContent value="users">
          <UsersPanel />
        </TabsContent>
        <TabsContent value="organizations">
          <OrganizationsPanel />
        </TabsContent>
        <TabsContent value="audit">
          <AuditPanel />
        </TabsContent>
      </Tabs>
    </main>
  );
}

// ---------------------------------------------------------------------------
// Users
// ---------------------------------------------------------------------------

function UsersPanel() {
  const { t } = useLang();
  const { user: me } = useAuth();
  const [rows, setRows] = useState<AdminUser[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Record<string, boolean>>({});
  const [resetFor, setResetFor] = useState<AdminUser | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      setRows(await listUsers(500));
    } catch (e) {
      setError(e instanceof AdminError ? e.message : t("auth.errorGeneric"));
    }
  }, [t]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function doTogglePromote(u: AdminUser) {
    setPending((p) => ({ ...p, [u.id]: true }));
    try {
      if (u.is_superuser) await demoteUser(u.id);
      else await promoteUser(u.id);
      await refresh();
    } catch (e) {
      setError(e instanceof AdminError ? e.message : t("auth.errorGeneric"));
    } finally {
      setPending((p) => ({ ...p, [u.id]: false }));
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("admin.users.title")}</CardTitle>
        <CardDescription>{t("admin.users.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        {error && (
          <div className="mb-4 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </div>
        )}
        {rows === null ? (
          <p className="text-sm text-muted-foreground">{t("auth.loading")}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="py-2 pr-3">{t("admin.users.col.email")}</th>
                  <th className="py-2 pr-3">{t("admin.users.col.name")}</th>
                  <th className="py-2 pr-3">{t("admin.users.col.role")}</th>
                  <th className="py-2 pr-3">{t("admin.users.col.createdAt")}</th>
                  <th className="py-2 pr-3 text-right">{t("admin.users.col.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((u) => {
                  const isSelf = me?.id === u.id;
                  const busy = !!pending[u.id];
                  return (
                    <tr key={u.id} className="border-b last:border-0">
                      <td className="py-2 pr-3 font-mono text-xs">{u.email}</td>
                      <td className="py-2 pr-3">{u.display_name ?? "—"}</td>
                      <td className="py-2 pr-3">
                        {u.is_superuser ? (
                          <Badge variant="default">{t("admin.users.role.admin")}</Badge>
                        ) : (
                          <Badge variant="secondary">{t("admin.users.role.member")}</Badge>
                        )}
                      </td>
                      <td className="py-2 pr-3 text-xs text-muted-foreground">{u.created_at}</td>
                      <td className="py-2 pr-3 text-right">
                        <div className="flex justify-end gap-2">
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={busy || (isSelf && u.is_superuser)}
                            title={isSelf && u.is_superuser ? t("admin.users.noSelfDemote") : ""}
                            onClick={() => doTogglePromote(u)}
                          >
                            {u.is_superuser
                              ? t("admin.users.action.demote")
                              : t("admin.users.action.promote")}
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={busy}
                            onClick={() => setResetFor(u)}
                          >
                            {t("admin.users.action.resetPassword")}
                          </Button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {resetFor && (
          <ResetPasswordForm
            user={resetFor}
            onClose={() => setResetFor(null)}
            onDone={() => {
              setResetFor(null);
              refresh();
            }}
          />
        )}
      </CardContent>
    </Card>
  );
}

function ResetPasswordForm({
  user,
  onClose,
  onDone,
}: {
  user: AdminUser;
  onClose: () => void;
  onDone: () => void;
}) {
  const { t } = useLang();
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await resetPassword(user.id, password);
      onDone();
    } catch (err) {
      setError(err instanceof AdminError ? err.message : t("auth.errorGeneric"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mt-6 rounded-md border border-primary/30 bg-primary/5 p-4">
      <div className="mb-3 flex items-start justify-between">
        <div>
          <p className="text-sm font-semibold">
            {t("admin.users.resetFor")}{" "}
            <span className="font-mono text-xs">{user.email}</span>
          </p>
          <p className="text-xs text-muted-foreground">
            {t("admin.users.resetHint")}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-sm text-muted-foreground hover:text-foreground"
          aria-label="close"
        >
          ✕
        </button>
      </div>
      <form onSubmit={onSubmit} className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <div className="flex-1">
          <label htmlFor="new-password" className="mb-1 block text-xs font-medium">
            {t("auth.field.password")}
          </label>
          <Input
            id="new-password"
            type="password"
            minLength={10}
            required
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <p className="mt-1 text-xs text-muted-foreground">{t("auth.passwordHint")}</p>
        </div>
        <Button type="submit" disabled={submitting}>
          {submitting ? t("admin.users.submitting") : t("admin.users.action.resetPassword")}
        </Button>
      </form>
      {error && (
        <div className="mt-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Organizations
// ---------------------------------------------------------------------------

function OrganizationsPanel() {
  const { t } = useLang();
  const [rows, setRows] = useState<AdminOrganization[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listOrganizations(500)
      .then(setRows)
      .catch((e) => setError(e instanceof AdminError ? e.message : t("auth.errorGeneric")));
  }, [t]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("admin.orgs.title")}</CardTitle>
        <CardDescription>{t("admin.orgs.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        {error && (
          <div className="mb-4 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </div>
        )}
        {rows === null ? (
          <p className="text-sm text-muted-foreground">{t("auth.loading")}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="py-2 pr-3">{t("admin.orgs.col.name")}</th>
                  <th className="py-2 pr-3">{t("admin.orgs.col.slug")}</th>
                  <th className="py-2 pr-3 text-right">{t("admin.orgs.col.members")}</th>
                  <th className="py-2 pr-3 text-right">{t("admin.orgs.col.scans")}</th>
                  <th className="py-2 pr-3">{t("admin.orgs.col.createdAt")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((o) => (
                  <tr key={o.id} className="border-b last:border-0">
                    <td className="py-2 pr-3 font-medium">{o.name}</td>
                    <td className="py-2 pr-3 font-mono text-xs">{o.slug}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">{o.member_count}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">{o.scan_count}</td>
                    <td className="py-2 pr-3 text-xs text-muted-foreground">{o.created_at}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Audit log
// ---------------------------------------------------------------------------

const AUDIT_ACTION_FILTERS = [
  "", // all
  "user.promote",
  "user.demote",
  "user.reset_password",
];

function AuditPanel() {
  const { t } = useLang();
  const [rows, setRows] = useState<AdminAuditEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionFilter, setActionFilter] = useState<string>("");

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const data = await listAudit({
        limit: 500,
        action: actionFilter || undefined,
      });
      setRows(data);
    } catch (e) {
      setError(e instanceof AdminError ? e.message : t("auth.errorGeneric"));
    }
  }, [t, actionFilter]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const labelFor = useMemo(
    () => (a: string) => a === "" ? t("admin.audit.filter.all") : a,
    [t],
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("admin.audit.title")}</CardTitle>
        <CardDescription>{t("admin.audit.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="mb-4 flex items-center gap-2">
          <label htmlFor="action-filter" className="text-sm text-muted-foreground">
            {t("admin.audit.filter.label")}
          </label>
          <select
            id="action-filter"
            className="h-9 rounded-md border border-input bg-background px-2 text-sm"
            value={actionFilter}
            onChange={(e) => setActionFilter(e.target.value)}
          >
            {AUDIT_ACTION_FILTERS.map((a) => (
              <option key={a || "all"} value={a}>
                {labelFor(a)}
              </option>
            ))}
          </select>
        </div>

        {error && (
          <div className="mb-4 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </div>
        )}

        {rows === null ? (
          <p className="text-sm text-muted-foreground">{t("auth.loading")}</p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("admin.audit.empty")}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="py-2 pr-3">{t("admin.audit.col.time")}</th>
                  <th className="py-2 pr-3">{t("admin.audit.col.actor")}</th>
                  <th className="py-2 pr-3">{t("admin.audit.col.action")}</th>
                  <th className="py-2 pr-3">{t("admin.audit.col.target")}</th>
                  <th className="py-2 pr-3">{t("admin.audit.col.details")}</th>
                  <th className="py-2 pr-3">{t("admin.audit.col.ip")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((e) => (
                  <tr key={e.id} className="border-b last:border-0 align-top">
                    <td className="py-2 pr-3 whitespace-nowrap text-xs text-muted-foreground">
                      {e.created_at}
                    </td>
                    <td className="py-2 pr-3 font-mono text-xs">
                      {e.actor_email ?? "—"}
                    </td>
                    <td className="py-2 pr-3">
                      <Badge variant="outline">{e.action}</Badge>
                    </td>
                    <td className="py-2 pr-3 font-mono text-xs">
                      {e.target_type && e.target_id
                        ? `${e.target_type}:${e.target_id}`
                        : "—"}
                    </td>
                    <td className="py-2 pr-3 font-mono text-xs">
                      {e.details ? JSON.stringify(e.details) : "—"}
                    </td>
                    <td className="py-2 pr-3 font-mono text-xs text-muted-foreground">
                      {e.ip ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
