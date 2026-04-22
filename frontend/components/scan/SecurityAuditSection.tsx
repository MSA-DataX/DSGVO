"use client";

import * as React from "react";
import {
  ShieldAlert, ShieldCheck, Shield, Lock, LockOpen, Info, ChevronDown, ChevronRight,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { severityColor } from "@/lib/utils";
import { useLang } from "@/lib/LanguageContext";
import type { SecurityAudit, TlsInfo } from "@/lib/types";

// Passive security observations grouped into one section so an operator
// can fix everything in one web-server config pass. The TLS strip up top
// is the fastest audit glance; header table below; info-leak + mixed-
// content panes at the end when they apply.

export function SecurityAuditSection({ audit }: { audit: SecurityAudit }) {
  const { t } = useLang();
  const [open, setOpen] = React.useState(true);

  if (audit.error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldAlert className="h-4 w-4" /> {t("security.title")}
          </CardTitle>
          <CardDescription>
            {t("security.error")} <code className="text-xs">{audit.error}</code>
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const highCount = audit.summary["headers_missing_or_weak_high"] ?? 0;
  const mediumCount = audit.summary["headers_missing_or_weak_medium"] ?? 0;
  const mixedSuffix = audit.mixed_content_count > 0
    ? t("security.mixed", { count: audit.mixed_content_count })
    : "";

  return (
    <Card>
      <CardHeader>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex w-full items-start justify-between gap-3 text-left"
        >
          <div>
            <CardTitle className="flex items-center gap-2">
              <ShieldAlert className="h-5 w-5" /> {t("security.title")}
            </CardTitle>
            <CardDescription>
              {t("security.desc", { high: highCount, medium: mediumCount, mixed: mixedSuffix })}
            </CardDescription>
          </div>
          {open ? (
            <ChevronDown className="mt-1 h-4 w-4 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-muted-foreground" />
          )}
        </button>
      </CardHeader>
      {open && (
        <CardContent className="space-y-4">
          {audit.tls && <TlsStrip tls={audit.tls} />}

          {audit.mixed_content_count > 0 && (
            <Alert variant="destructive">
              <LockOpen className="h-4 w-4" />
              <AlertTitle>{t("security.mixedTitle", { count: audit.mixed_content_count })}</AlertTitle>
              <AlertDescription>
                {t("security.mixedDesc")}
                {audit.mixed_content_samples.length > 0 && (
                  <ul className="mt-2 list-inside list-disc font-mono text-[11px]">
                    {audit.mixed_content_samples.map((u, i) => (
                      <li key={i} className="break-all">{u}</li>
                    ))}
                  </ul>
                )}
              </AlertDescription>
            </Alert>
          )}

          <HeadersTable audit={audit} />

          {audit.info_leak_headers.length > 0 && (
            <div className="rounded-md border p-3">
              <div className="mb-2 flex items-center gap-2">
                <Info className="h-4 w-4 text-muted-foreground" />
                <span className="text-sm font-medium">{t("security.infoLeak.title")}</span>
              </div>
              <ul className="space-y-1 text-xs">
                {audit.info_leak_headers.map((h, i) => (
                  <li key={i}>
                    <code className="font-mono text-[11px]">{h.name}: {h.value}</code>{" "}
                    <span className="text-muted-foreground">— {h.leaks}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Phase 5 — DNS / SRI / security.txt, each only rendered
              when the underlying probe produced data. Kept compact so
              the main section doesn't balloon. */}
          {audit.dns && <DnsStrip dns={audit.dns} />}
          {(audit.sri_missing && audit.sri_missing.length > 0) ? (
            <div className="rounded-md border border-risk-medium/40 bg-risk-medium/5 p-3 text-sm">
              <div className="flex items-center gap-2 text-risk-medium">
                <Shield className="h-4 w-4" />
                <span className="font-medium">{t("security.sri.title")}</span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                {t("security.sri.missing", { count: audit.sri_missing.length })}
              </p>
              <ul className="mt-2 list-inside list-disc font-mono text-[11px] text-muted-foreground">
                {audit.sri_missing.slice(0, 5).map((u, i) => (
                  <li key={i} className="break-all">{u}</li>
                ))}
                {audit.sri_missing.length > 5 && (
                  <li>+{audit.sri_missing.length - 5} more</li>
                )}
              </ul>
            </div>
          ) : null}
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className="font-medium">{t("security.securityTxt.title")}:</span>
            {audit.security_txt_url ? (
              <Badge className="bg-risk-low/10 text-risk-low text-[10px]">
                {t("security.securityTxt.present")}
              </Badge>
            ) : (
              <Badge className="bg-muted text-muted-foreground text-[10px]">
                {t("security.securityTxt.missing")}
              </Badge>
            )}
          </div>

          <p className="text-[11px] text-muted-foreground">{t("security.footer")}</p>
        </CardContent>
      )}
    </Card>
  );
}

function DnsStrip({ dns }: { dns: import("@/lib/types").DnsSecurityInfo }) {
  const { t } = useLang();
  const items: Array<{ label: string; ok: boolean; extra?: string }> = [
    {
      label: t("security.dns.spf"),
      ok: dns.spf_present,
    },
    {
      label: t("security.dns.dmarc"),
      ok: dns.dmarc_present && dns.dmarc_policy !== "none",
      extra: dns.dmarc_present ? `p=${dns.dmarc_policy}` : undefined,
    },
    { label: t("security.dns.dnssec"), ok: dns.dnssec_enabled },
    { label: t("security.dns.caa"),    ok: dns.caa_present },
  ];
  return (
    <div>
      <div className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
        {t("security.dns.title")} — {dns.domain}
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {items.map((it, i) => (
          <div
            key={i}
            className={`rounded-md border p-2 text-xs ${
              it.ok ? "border-risk-low/50" : "border-risk-high/50"
            }`}
          >
            <div className="font-medium">{it.label}</div>
            <div className={it.ok ? "text-risk-low" : "text-risk-high"}>
              {it.ok ? t("security.dns.present") : t("security.dns.missing")}
              {it.extra && <span className="ml-1 text-muted-foreground">({it.extra})</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function TlsStrip({ tls }: { tls: TlsInfo }) {
  const { t } = useLang();
  const httpsOk = tls.https_enforced;
  const tlsOk = tls.tls_version === "TLSv1.3" || tls.tls_version === "TLSv1.2";
  const certOk = (tls.cert_expires_days ?? 999) > 14;
  const certCritical = (tls.cert_expires_days ?? 999) < 0;
  const certSoon = (tls.cert_expires_days ?? 999) >= 0 && (tls.cert_expires_days ?? 999) < 14;
  const hstsOk = (tls.hsts_max_age_days ?? 0) >= 180;

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <TlsStat
        label={t("security.tls.httpsEnforced")}
        ok={httpsOk}
        value={httpsOk ? t("security.tls.yes") : t("security.tls.noHttp")}
      />
      <TlsStat
        label={t("security.tls.version")}
        ok={tlsOk}
        value={tls.tls_version ?? t("security.tls.unknown")}
      />
      <TlsStat
        label={t("security.tls.certExpires")}
        ok={certOk && !certCritical}
        warning={certSoon}
        critical={certCritical}
        value={
          tls.cert_expires_days == null
            ? t("security.tls.unknown")
            : tls.cert_expires_days < 0
            ? t("security.tls.ago", { days: Math.abs(tls.cert_expires_days) })
            : t("security.tls.in", { days: tls.cert_expires_days })
        }
      />
      <TlsStat
        label={t("security.tls.hsts")}
        ok={hstsOk}
        value={
          tls.hsts_max_age_days == null
            ? t("security.tls.missing")
            : `${tls.hsts_max_age_days}d${tls.hsts_preload_eligible ? t("security.tls.preloadReady") : ""}`
        }
      />
    </div>
  );
}

function TlsStat({
  label,
  ok,
  value,
  warning,
  critical,
}: {
  label: string;
  ok: boolean;
  value: string;
  warning?: boolean;
  critical?: boolean;
}) {
  const color = critical
    ? "border-risk-critical text-risk-critical"
    : warning
    ? "border-risk-medium text-risk-medium"
    : ok
    ? "border-risk-low text-risk-low"
    : "border-risk-high text-risk-high";
  return (
    <div className={`rounded-md border p-2 ${color}`}>
      <div className="flex items-center gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
        {ok && !warning && !critical ? <Lock className="h-3 w-3" /> : <LockOpen className="h-3 w-3" />}
        {label}
      </div>
      <div className="mt-1 text-sm font-medium">{value}</div>
    </div>
  );
}

function HeadersTable({ audit }: { audit: SecurityAudit }) {
  const { t } = useLang();
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
            <th className="py-2 pr-3">{t("security.h.header")}</th>
            <th className="py-2 pr-3">{t("security.h.status")}</th>
            <th className="py-2 pr-3">{t("security.h.severity")}</th>
            <th className="py-2 pr-3">{t("security.h.note")}</th>
          </tr>
        </thead>
        <tbody>
          {audit.headers.map((h, i) => (
            <tr key={i} className="border-b last:border-b-0 align-top">
              <td className="py-2 pr-3 font-mono text-xs">{h.name}</td>
              <td className="py-2 pr-3">
                {h.present ? (
                  <Badge className="bg-risk-low/10 text-risk-low text-[10px]">
                    <ShieldCheck className="mr-1 h-3 w-3" />
                    {t("security.header.present")}
                  </Badge>
                ) : (
                  <Badge className="bg-risk-high/10 text-risk-high text-[10px]">
                    <ShieldAlert className="mr-1 h-3 w-3" />
                    {t("security.header.missing")}
                  </Badge>
                )}
              </td>
              <td className="py-2 pr-3">
                <Badge className={severityColor(h.severity)}>{t(`severity.${h.severity}`)}</Badge>
              </td>
              <td className="py-2 pr-3 text-xs text-muted-foreground">{h.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
