"use client";

import * as React from "react";
import {
  ShieldAlert, ShieldCheck, Lock, LockOpen, Info, ChevronDown, ChevronRight,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { severityColor } from "@/lib/utils";
import type { SecurityAudit, TlsInfo } from "@/lib/types";

// Passive security observations grouped into one section so an operator
// can fix everything in one web-server config pass. The TLS strip up top
// is the fastest audit glance; header table below; info-leak + mixed-
// content panes at the end when they apply.

export function SecurityAuditSection({ audit }: { audit: SecurityAudit }) {
  const [open, setOpen] = React.useState(true);

  if (audit.error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldAlert className="h-4 w-4" /> Security audit
          </CardTitle>
          <CardDescription>
            Audit could not complete: <code className="text-xs">{audit.error}</code>
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const highCount = audit.summary["headers_missing_or_weak_high"] ?? 0;
  const mediumCount = audit.summary["headers_missing_or_weak_medium"] ?? 0;

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
              <ShieldAlert className="h-5 w-5" /> Security audit
            </CardTitle>
            <CardDescription>
              Passive check: HTTP headers, TLS, mixed content. {highCount} critical,{" "}
              {mediumCount} medium issue(s). {audit.mixed_content_count > 0 ? `${audit.mixed_content_count} mixed-content request(s).` : ""}
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
              <AlertTitle>{audit.mixed_content_count} mixed-content request(s)</AlertTitle>
              <AlertDescription>
                HTTPS page loads resource(s) over plain HTTP. Browser padlock is misleading —
                transport encryption only protects the shell, not the loaded assets.
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
                <span className="text-sm font-medium">Information leak in response headers</span>
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

          <p className="text-[11px] text-muted-foreground">
            All checks are passive (same info any browser visit reveals). No active probing,
            no directory bruteforce, no exploit attempts — compliant with § 202c StGB.
          </p>
        </CardContent>
      )}
    </Card>
  );
}

function TlsStrip({ tls }: { tls: TlsInfo }) {
  const httpsOk = tls.https_enforced;
  const tlsOk = tls.tls_version === "TLSv1.3" || tls.tls_version === "TLSv1.2";
  const certOk = (tls.cert_expires_days ?? 999) > 14;
  const certCritical = (tls.cert_expires_days ?? 999) < 0;
  const certSoon = (tls.cert_expires_days ?? 999) >= 0 && (tls.cert_expires_days ?? 999) < 14;
  const hstsOk = (tls.hsts_max_age_days ?? 0) >= 180;

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <TlsStat
        label="HTTPS enforced"
        ok={httpsOk}
        value={httpsOk ? "yes" : "NO — plain HTTP reachable"}
      />
      <TlsStat
        label="TLS version"
        ok={tlsOk}
        value={tls.tls_version ?? "unknown"}
      />
      <TlsStat
        label="Cert expires"
        ok={certOk && !certCritical}
        warning={certSoon}
        critical={certCritical}
        value={
          tls.cert_expires_days == null
            ? "unknown"
            : tls.cert_expires_days < 0
            ? `${Math.abs(tls.cert_expires_days)}d AGO`
            : `in ${tls.cert_expires_days}d`
        }
      />
      <TlsStat
        label="HSTS"
        ok={hstsOk}
        value={
          tls.hsts_max_age_days == null
            ? "missing"
            : `${tls.hsts_max_age_days}d${tls.hsts_preload_eligible ? " · preload-ready" : ""}`
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
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
            <th className="py-2 pr-3">Header</th>
            <th className="py-2 pr-3">Status</th>
            <th className="py-2 pr-3">Severity if missing</th>
            <th className="py-2 pr-3">Note</th>
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
                    present
                  </Badge>
                ) : (
                  <Badge className="bg-risk-high/10 text-risk-high text-[10px]">
                    <ShieldAlert className="mr-1 h-3 w-3" />
                    missing
                  </Badge>
                )}
              </td>
              <td className="py-2 pr-3">
                <Badge className={severityColor(h.severity)}>{h.severity}</Badge>
              </td>
              <td className="py-2 pr-3 text-xs text-muted-foreground">{h.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
