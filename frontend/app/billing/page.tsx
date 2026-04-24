"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { RequireAuth } from "@/components/auth/RequireAuth";
import { UserMenu } from "@/components/auth/UserMenu";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import {
  BillingError,
  cancelSubscription,
  formatEuro,
  getPlans,
  getSubscription,
  startCheckout,
} from "@/lib/billing";
import { useLang } from "@/lib/LanguageContext";
import type { PlanView, SubscriptionView } from "@/lib/types";

export default function BillingPage() {
  return (
    <RequireAuth>
      <BillingDashboard />
    </RequireAuth>
  );
}

function BillingDashboard() {
  const { t, lang } = useLang();
  const searchParams = useSearchParams();
  const [subscription, setSubscription] = useState<SubscriptionView | null>(null);
  const [plans, setPlans] = useState<PlanView[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);   // plan_code currently pending

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const [sub, pl] = await Promise.all([getSubscription(), getPlans()]);
      setSubscription(sub);
      setPlans(pl);
    } catch (e) {
      setError(e instanceof BillingError ? e.message : t("auth.errorGeneric"));
    }
  }, [t]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const isReturnFromMollie = searchParams.get("status") === "return";

  async function onUpgrade(planCode: string) {
    setBusy(planCode);
    setError(null);
    try {
      const { checkout_url } = await startCheckout(planCode);
      window.location.assign(checkout_url);
    } catch (e) {
      setError(e instanceof BillingError ? e.message : t("auth.errorGeneric"));
      setBusy(null);
    }
  }

  async function onCancel() {
    if (!window.confirm(t("billing.cancel.confirm"))) return;
    setBusy("cancel");
    setError(null);
    setMessage(null);
    try {
      await cancelSubscription();
      setMessage(t("billing.cancel.done"));
      await refresh();
    } catch (e) {
      setError(e instanceof BillingError ? e.message : t("auth.errorGeneric"));
    } finally {
      setBusy(null);
    }
  }

  return (
    <main className="container mx-auto max-w-6xl py-8">
      <header className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold">{t("billing.title")}</h1>
          <p className="text-sm text-muted-foreground">{t("billing.subtitle")}</p>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/" className="text-sm text-muted-foreground hover:underline">
            ← {t("billing.backToDashboard")}
          </Link>
          <LanguageSwitcher />
          <UserMenu />
        </div>
      </header>

      {isReturnFromMollie && (
        <div className="mb-4 flex items-center justify-between rounded-md border border-primary/40 bg-primary/5 px-4 py-3 text-sm">
          <span>{t("billing.return.banner")}</span>
          <Button size="sm" variant="outline" onClick={() => refresh()}>
            {t("billing.refresh")}
          </Button>
        </div>
      )}

      {error && (
        <div className="mb-4 rounded-md border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}
      {message && (
        <div className="mb-4 rounded-md border border-emerald-500/40 bg-emerald-500/10 px-4 py-3 text-sm">
          {message}
        </div>
      )}

      <CurrentPlanCard subscription={subscription} lang={lang} t={t} />

      <div className="mt-6">
        <h2 className="text-xl font-semibold">{t("billing.plans.title")}</h2>
        <p className="mb-4 text-sm text-muted-foreground">{t("billing.plans.subtitle")}</p>
        {plans === null ? (
          <p className="text-sm text-muted-foreground">{t("auth.loading")}</p>
        ) : (
          <div className="grid gap-4 md:grid-cols-3">
            {plans.map((p) => (
              <PlanCard
                key={p.code}
                plan={p}
                lang={lang}
                t={t}
                currentCode={subscription?.plan.code}
                subscriptionStatus={subscription?.status}
                busy={busy === p.code}
                disabledAll={busy !== null}
                onUpgrade={() => onUpgrade(p.code)}
              />
            ))}
          </div>
        )}
      </div>

      {subscription
        && subscription.status !== "no_subscription"
        && subscription.status !== "canceled"
        && !subscription.plan.is_free && (
        <Card className="mt-6 border-destructive/30">
          <CardHeader>
            <CardTitle className="text-base">{t("billing.cancel.title")}</CardTitle>
            <CardDescription>{t("billing.cancel.description")}</CardDescription>
          </CardHeader>
          <CardContent>
            <Button
              variant="outline"
              className="border-destructive/40 text-destructive hover:bg-destructive/10"
              disabled={busy !== null}
              onClick={onCancel}
            >
              {busy === "cancel" ? t("billing.cancel.submitting") : t("billing.cancel.button")}
            </Button>
          </CardContent>
        </Card>
      )}
    </main>
  );
}

// ---------------------------------------------------------------------------
// Current plan + usage bar
// ---------------------------------------------------------------------------

function CurrentPlanCard({
  subscription,
  lang,
  t,
}: {
  subscription: SubscriptionView | null;
  lang: string;
  t: (k: string, v?: Record<string, string | number>) => string;
}) {
  if (subscription === null) {
    return (
      <Card>
        <CardContent className="py-6">
          <p className="text-sm text-muted-foreground">{t("auth.loading")}</p>
        </CardContent>
      </Card>
    );
  }

  const { plan, status, current_period_start, scans_used, scans_quota } = subscription;
  const unlimited = plan.is_unlimited;
  const pct = unlimited
    ? 0
    : Math.min(100, Math.round((scans_used / Math.max(1, scans_quota)) * 100));
  const locale = lang === "de" ? "de-DE" : "en-GB";

  const statusLabel = t(`billing.status.${status}`);
  const priceLabel = plan.is_free
    ? t("billing.plans.free")
    : `${formatEuro(plan.price_eur_cents, locale)}${t("billing.plans.perMonth")}`;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("billing.current.title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label={t("billing.current.plan")}>
            <span className="font-semibold">{plan.name}</span>
            <span className="ml-2 text-sm text-muted-foreground">{priceLabel}</span>
          </Field>
          <Field label={t("billing.current.status")}>
            <StatusBadge status={status} label={statusLabel} />
          </Field>
          <Field label={t("billing.current.periodStart")}>
            <span className="text-sm text-muted-foreground">
              {current_period_start.slice(0, 10)}
            </span>
          </Field>
        </div>

        <div>
          <div className="mb-1 flex items-baseline justify-between text-sm">
            <span>{t("billing.current.usage")}</span>
            <span className="tabular-nums text-muted-foreground">
              {unlimited
                ? `${scans_used} · ${t("billing.current.unlimited")}`
                : `${scans_used} / ${scans_quota}`}
            </span>
          </div>
          {!unlimited && (
            <Progress
              value={pct}
              indicatorClassName={
                pct >= 100 ? "bg-destructive" : pct >= 80 ? "bg-amber-500" : "bg-primary"
              }
            />
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mt-1">{children}</div>
    </div>
  );
}

function StatusBadge({ status, label }: { status: string; label: string }) {
  const tone: "default" | "secondary" | "outline" | "destructive" =
    status === "active" ? "default"
      : status === "past_due" ? "destructive"
      : status === "canceled" ? "outline"
      : "secondary";
  return <Badge variant={tone}>{label}</Badge>;
}

// ---------------------------------------------------------------------------
// Plan card (grid entry)
// ---------------------------------------------------------------------------

function PlanCard({
  plan,
  t,
  lang,
  currentCode,
  subscriptionStatus,
  busy,
  disabledAll,
  onUpgrade,
}: {
  plan: PlanView;
  t: (k: string, v?: Record<string, string | number>) => string;
  lang: string;
  currentCode?: string;
  subscriptionStatus?: string;
  busy: boolean;
  disabledAll: boolean;
  onUpgrade: () => void;
}) {
  const locale = lang === "de" ? "de-DE" : "en-GB";
  const isCurrent =
    currentCode === plan.code && subscriptionStatus !== "no_subscription";
  const priceLabel = plan.is_free
    ? t("billing.plans.free")
    : formatEuro(plan.price_eur_cents, locale);
  const quotaLabel = plan.is_unlimited
    ? t("billing.plans.scansUnlimited")
    : t("billing.plans.scansMonth", { n: plan.monthly_scan_quota });

  const canUpgrade = !plan.is_free && !isCurrent;

  return (
    <Card className={isCurrent ? "border-primary/60" : ""}>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>{plan.name}</span>
          {isCurrent && <Badge variant="secondary">{t("billing.plans.current")}</Badge>}
        </CardTitle>
        <div className="mt-1 text-2xl font-bold">
          {priceLabel}
          {!plan.is_free && (
            <span className="ml-1 text-sm font-normal text-muted-foreground">
              {t("billing.plans.perMonth")}
            </span>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-muted-foreground">{plan.description}</p>
        <p className="text-sm font-medium">{quotaLabel}</p>
        {canUpgrade && (
          <Button
            className="w-full"
            disabled={disabledAll}
            onClick={onUpgrade}
          >
            {busy ? t("auth.loading") : t("billing.plans.upgrade")}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
