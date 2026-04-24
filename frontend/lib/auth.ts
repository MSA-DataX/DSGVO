/** Client-side auth API — talks only to /api/auth/*, never the backend directly. */

export interface AuthUser {
  id: string;
  email: string;
  display_name: string | null;
  is_superuser?: boolean;
}

export class AuthError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "AuthError";
  }
}

async function parseError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    // FastAPI errors: { detail: "..." } or { detail: [{msg: "..."}, ...] }
    if (typeof body?.detail === "string") return body.detail;
    if (Array.isArray(body?.detail) && body.detail.length > 0) {
      return body.detail.map((d: { msg?: string }) => d?.msg ?? JSON.stringify(d)).join("; ");
    }
    if (typeof body?.error === "string") return body.error;
    return JSON.stringify(body);
  } catch {
    return res.statusText || `HTTP ${res.status}`;
  }
}

export async function signup(params: {
  email: string;
  password: string;
  display_name?: string;
  organization_name?: string;
}): Promise<AuthUser> {
  const res = await fetch("/api/auth/signup", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new AuthError(res.status, await parseError(res));
  const body = (await res.json()) as { user: AuthUser };
  return body.user;
}

export async function login(email: string, password: string): Promise<AuthUser> {
  const res = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new AuthError(res.status, await parseError(res));
  const body = (await res.json()) as { user: AuthUser };
  return body.user;
}

export async function logout(): Promise<void> {
  await fetch("/api/auth/logout", { method: "POST" });
}

/** Returns the current user, or null when no valid session cookie is present. */
export async function fetchMe(): Promise<AuthUser | null> {
  const res = await fetch("/api/auth/me");
  if (res.status === 401) return null;
  if (!res.ok) throw new AuthError(res.status, await parseError(res));
  return (await res.json()) as AuthUser;
}
