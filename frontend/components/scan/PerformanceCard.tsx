"use client";

import * as React from "react";
import { Gauge, AlertTriangle } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { useLang } from "@/lib/LanguageContext";
import type { PerformanceReport, WebVitals } from "@/lib/types";

// Phase 11 — Performance suite UI.
//
// Three tabs map 1:1 to the backend submodules: Web Vitals, Network,
// Assets. Score is linear 0-100 with a fully-traceable breakdown — the
// header strip shows each contribution as "-N pts (label)" so an
// auditor reading the dashboard can derive the score by hand.
//
// Color thresholds match Google's "Good/Needs improvement/Poor" buckets
// (see web.dev/vitals) so a customer who already lives in PageSpeed
// Insights sees the same red/amber/green they'd see there.

export function PerformanceCard({ report }: { report: PerformanceReport }) {
  const { t } = useLang();
  if (report.error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Gauge className="h-5 w-5" /> {t("perf.title")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertTitle>{t("perf.error.title")}</AlertTitle>
            <AlertDescription className="font-mono text-xs">
              {report.error}
            </AlertDescription>
          </Alert>
        </CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Gauge className="h-5 w-5" /> {t("perf.title")}
            </CardTitle>
            <CardDescription>{t("perf.subtitle")}</CardDescription>
          </div>
          <div className="text-right">
            <div className={`text-3xl font-bold ${scoreColor(report.score)}`}>
              {report.score}
              <span className="text-sm font-normal text-muted-foreground">/100</span>
            </div>
            <div className="mt-1 text-[10px] uppercase tracking-wide text-muted-foreground">
              {t("perf.score.linear")}
            </div>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <ScoreBreakdown breakdown={report.score_breakdown} />
        <Tabs defaultValue="vitals">
          <TabsList>
            <TabsTrigger value="vitals">{t("perf.tab.vitals")}</TabsTrigger>
            <TabsTrigger value="network">{t("perf.tab.network")}</TabsTrigger>
            <TabsTrigger value="assets">{t("perf.tab.assets")}</TabsTrigger>
          </TabsList>
          <TabsContent value="vitals" className="mt-4">
            <VitalsTab vitals={report.web_vitals} />
          </TabsContent>
          <TabsContent value="network" className="mt-4">
            <NetworkTab metrics={report.network_metrics} />
          </TabsContent>
          <TabsContent value="assets" className="mt-4">
            <AssetsTab audit={report.asset_audit} />
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}

// -- Score header ---------------------------------------------------------

function ScoreBreakdown({ breakdown }: { breakdown: Record<string, number> }) {
  const { t } = useLang();
  const entries = Object.entries(breakdown).filter(([, v]) => v < 0);
  if (entries.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">{t("perf.breakdown.clean")}</p>
    );
  }
  return (
    <div>
      <div className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
        {t("perf.breakdown.title")}
      </div>
      <ul className="flex flex-wrap gap-1.5">
        {entries.map(([key, val]) => (
          <li key={key}>
            <Badge className="bg-risk-medium/15 text-risk-medium font-mono text-[11px]">
              {val} {t(`perf.breakdown.${key}`)}
            </Badge>
          </li>
        ))}
      </ul>
    </div>
  );
}

// -- Vitals tab -----------------------------------------------------------

function VitalsTab({ vitals }: { vitals: WebVitals }) {
  const { t } = useLang();
  return (
    <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      <VitalCell
        label={t("perf.vital.lcp")}
        value={vitals.lcp_ms}
        format={fmtMs}
        good={2500}
        poor={4000}
        hint={t("perf.vital.lcp.hint")}
      />
      <VitalCell
        label={t("perf.vital.inp")}
        value={vitals.inp_ms}
        format={fmtMs}
        good={200}
        poor={500}
        hint={t("perf.vital.inp.hint")}
      />
      <VitalCell
        label={t("perf.vital.cls")}
        value={vitals.cls}
        format={(n) => n.toFixed(3)}
        good={0.1}
        poor={0.25}
        hint={t("perf.vital.cls.hint")}
      />
      <VitalCell
        label={t("perf.vital.fcp")}
        value={vitals.fcp_ms}
        format={fmtMs}
        good={1800}
        poor={3000}
        hint={t("perf.vital.fcp.hint")}
      />
      <VitalCell
        label={t("perf.vital.ttfb")}
        value={vitals.ttfb_ms}
        format={fmtMs}
        good={800}
        poor={1800}
        hint={t("perf.vital.ttfb.hint")}
      />
    </ul>
  );
}

function VitalCell({
  label, value, format, good, poor, hint,
}: {
  label: string;
  value: number | null;
  format: (n: number) => string;
  good: number;
  poor: number;
  hint: string;
}) {
  const { t } = useLang();
  const color =
    value === null ? "text-muted-foreground"
      : value <= good ? "text-risk-low"
      : value >= poor ? "text-risk-high"
      : "text-risk-medium";
  return (
    <li className="rounded-md border p-3" title={hint}>
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className={`mt-1 text-2xl font-semibold ${color}`}>
        {value === null ? "—" : format(value)}
      </div>
      <div className="mt-1 text-[10px] text-muted-foreground">
        {value === null ? t("perf.vital.notMeasured") : `${t("perf.vital.target")} ≤ ${format(good)}`}
      </div>
    </li>
  );
}

// -- Network tab ----------------------------------------------------------

function NetworkTab({ metrics }: { metrics: PerformanceReport["network_metrics"] }) {
  const { t } = useLang();
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label={t("perf.network.requests")} value={String(metrics.total_requests)} />
        <Stat label={t("perf.network.transfer")} value={fmtBytes(metrics.total_transfer_bytes)} />
        <Stat label={t("perf.network.thirdParty")} value={String(metrics.third_party_request_count)} />
        <Stat label={t("perf.network.thirdPartyBytes")} value={fmtBytes(metrics.third_party_transfer_bytes)} />
      </div>
      {Object.keys(metrics.requests_by_type).length > 0 && (
        <div>
          <div className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
            {t("perf.network.byType")}
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th className="py-1.5">{t("perf.network.h.type")}</th>
                <th className="py-1.5 text-right">{t("perf.network.h.count")}</th>
                <th className="py-1.5 text-right">{t("perf.network.h.bytes")}</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(metrics.requests_by_type)
                .sort((a, b) => (metrics.bytes_by_type[b[0]] ?? 0) - (metrics.bytes_by_type[a[0]] ?? 0))
                .map(([type, count]) => (
                  <tr key={type} className="border-b last:border-b-0">
                    <td className="py-1.5 font-mono text-xs">{type}</td>
                    <td className="py-1.5 text-right font-mono text-xs">{count}</td>
                    <td className="py-1.5 text-right font-mono text-xs">
                      {fmtBytes(metrics.bytes_by_type[type] ?? 0)}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}
      {metrics.render_blocking.length > 0 && (
        <div>
          <div className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
            {t("perf.network.renderBlocking", { count: metrics.render_blocking.length })}
          </div>
          <ul className="space-y-1">
            {metrics.render_blocking.slice(0, 10).map((r, i) => (
              <li key={i} className="flex items-center gap-2 text-xs">
                <Badge variant="outline" className="text-[10px]">{r.resource_type}</Badge>
                <span className="truncate font-mono text-muted-foreground">{r.url}</span>
                {r.size_bytes !== null && (
                  <span className="ml-auto font-mono">{fmtBytes(r.size_bytes)}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// -- Assets tab -----------------------------------------------------------

function AssetsTab({ audit }: { audit: PerformanceReport["asset_audit"] }) {
  const { t } = useLang();
  const total = audit.oversized_images.length + audit.oversized_scripts.length + audit.uncompressed_responses.length;
  if (total === 0) {
    return <p className="text-sm text-muted-foreground">{t("perf.assets.clean")}</p>;
  }
  return (
    <div className="space-y-4">
      <AssetList
        title={t("perf.assets.oversizedImages", { count: audit.oversized_images.length })}
        items={audit.oversized_images.map((a) => ({
          url: a.url,
          right: `${fmtBytes(a.size_bytes)} (>${fmtBytes(a.threshold_bytes)})`,
        }))}
      />
      <AssetList
        title={t("perf.assets.oversizedScripts", { count: audit.oversized_scripts.length })}
        items={audit.oversized_scripts.map((a) => ({
          url: a.url,
          right: `${fmtBytes(a.size_bytes)} (>${fmtBytes(a.threshold_bytes)})`,
        }))}
      />
      <AssetList
        title={t("perf.assets.uncompressed", { count: audit.uncompressed_responses.length })}
        items={audit.uncompressed_responses.map((a) => ({
          url: a.url,
          right: `${fmtBytes(a.size_bytes)} · ${a.content_encoding ?? "identity"}`,
        }))}
      />
    </div>
  );
}

function AssetList({
  title,
  items,
}: {
  title: string;
  items: { url: string; right: string }[];
}) {
  if (items.length === 0) return null;
  return (
    <div>
      <div className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">{title}</div>
      <ul className="space-y-1">
        {items.slice(0, 10).map((it, i) => (
          <li key={i} className="flex items-center gap-2 text-xs">
            <span className="truncate font-mono text-muted-foreground">{it.url}</span>
            <span className="ml-auto font-mono">{it.right}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// -- Helpers --------------------------------------------------------------

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border p-3">
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-1 text-xl font-semibold">{value}</div>
    </div>
  );
}

function fmtMs(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(2)} s`;
  return `${Math.round(n)} ms`;
}

function fmtBytes(n: number): string {
  if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(2)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${n} B`;
}

function scoreColor(score: number): string {
  if (score >= 80) return "text-risk-low";
  if (score >= 50) return "text-risk-medium";
  return "text-risk-high";
}
