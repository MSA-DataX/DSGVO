/** Client-side billing API — wraps /api/billing/*. Pairs with the
 *  backend routes in app/routers/billing.py. */

import type {
  CheckoutResponse,
  PlanView,
  SubscriptionView,
} from "./types";

export class BillingError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "BillingError";
  }
}

async function parseError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    // FastAPI errors: { detail: string } or { detail: { message: ... } }
    // for the 402 quota-over case.
    if (typeof body?.detail === "string") return body.detail;
    if (body?.detail && typeof body.detail === "object") {
      return typeof body.detail.message === "string"
        ? body.detail.message
        : JSON.stringify(body.detail);
    }
    return JSON.stringify(body);
  } catch {
    return res.statusText || `HTTP ${res.status}`;
  }
}

export async function getPlans(): Promise<PlanView[]> {
  const res = await fetch("/api/billing/plans");
  if (!res.ok) throw new BillingError(res.status, await parseError(res));
  return (await res.json()) as PlanView[];
}

export async function getSubscription(): Promise<SubscriptionView> {
  const res = await fetch("/api/billing/subscription");
  if (!res.ok) throw new BillingError(res.status, await parseError(res));
  return (await res.json()) as SubscriptionView;
}

/** Kicks off a Mollie checkout. Returns the URL the browser should
 *  redirect to — caller is responsible for `window.location.assign`. */
export async function startCheckout(planCode: string): Promise<CheckoutResponse> {
  const res = await fetch("/api/billing/checkout", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ plan_code: planCode }),
  });
  if (!res.ok) throw new BillingError(res.status, await parseError(res));
  return (await res.json()) as CheckoutResponse;
}

export async function cancelSubscription(): Promise<{ status: string }> {
  const res = await fetch("/api/billing/cancel", { method: "POST" });
  if (!res.ok) throw new BillingError(res.status, await parseError(res));
  return (await res.json()) as { status: string };
}

/** UI helper — "€19.00" from 1900 cents. Matches the backend's
 *  `_cents_to_mollie` format but localised for display. */
export function formatEuro(cents: number, locale = "en-EU"): string {
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: cents % 100 === 0 ? 0 : 2,
  }).format(cents / 100);
}
