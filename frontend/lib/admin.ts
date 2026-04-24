/** Client-side wrappers for /api/admin/*. Thin pass-throughs — all the
 *  interesting behaviour (auth, audit logging, authorization) happens
 *  in the backend. These just surface typed results and errors. */

import type {
  AdminAuditEntry,
  AdminOrganization,
  AdminUser,
} from "./types";

export class AdminError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "AdminError";
  }
}

async function parseError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
    if (Array.isArray(body?.detail) && body.detail.length > 0) {
      return body.detail.map((d: { msg?: string }) => d?.msg ?? JSON.stringify(d)).join("; ");
    }
    return JSON.stringify(body);
  } catch {
    return res.statusText || `HTTP ${res.status}`;
  }
}

export async function listUsers(limit = 100): Promise<AdminUser[]> {
  const res = await fetch(`/api/admin/users?limit=${limit}`);
  if (!res.ok) throw new AdminError(res.status, await parseError(res));
  return (await res.json()) as AdminUser[];
}

export async function listOrganizations(limit = 100): Promise<AdminOrganization[]> {
  const res = await fetch(`/api/admin/organizations?limit=${limit}`);
  if (!res.ok) throw new AdminError(res.status, await parseError(res));
  return (await res.json()) as AdminOrganization[];
}

export async function listAudit(params: {
  limit?: number;
  action?: string;
  actor_user_id?: string;
} = {}): Promise<AdminAuditEntry[]> {
  const qs = new URLSearchParams();
  if (params.limit != null) qs.set("limit", String(params.limit));
  if (params.action) qs.set("action", params.action);
  if (params.actor_user_id) qs.set("actor_user_id", params.actor_user_id);
  const res = await fetch(`/api/admin/audit${qs.toString() ? `?${qs}` : ""}`);
  if (!res.ok) throw new AdminError(res.status, await parseError(res));
  return (await res.json()) as AdminAuditEntry[];
}

export async function promoteUser(id: string): Promise<void> {
  const res = await fetch(`/api/admin/users/${encodeURIComponent(id)}/promote`, {
    method: "POST",
  });
  if (!res.ok) throw new AdminError(res.status, await parseError(res));
}

export async function demoteUser(id: string): Promise<void> {
  const res = await fetch(`/api/admin/users/${encodeURIComponent(id)}/demote`, {
    method: "POST",
  });
  if (!res.ok) throw new AdminError(res.status, await parseError(res));
}

export async function resetPassword(id: string, newPassword: string): Promise<void> {
  const res = await fetch(
    `/api/admin/users/${encodeURIComponent(id)}/reset-password`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ new_password: newPassword }),
    },
  );
  if (!res.ok) throw new AdminError(res.status, await parseError(res));
}
