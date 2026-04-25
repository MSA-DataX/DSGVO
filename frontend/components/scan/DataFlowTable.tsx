"use client";

import { Radar } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { countryColor, severityColor } from "@/lib/utils";
import { useLang } from "@/lib/LanguageContext";
import type { NetworkResult } from "@/lib/types";

export function DataFlowTable({ network }: { network: NetworkResult }) {
  const { t } = useLang();
  const sorted = [...network.data_flow].sort((a, b) => {
    const order = { high: 0, medium: 1, low: 2 } as const;
    return order[a.risk] - order[b.risk] || b.request_count - a.request_count;
  });
  // Phase 9c — pre-consent tracking-pixel hits. We dedupe by registered
  // domain so a site that fires 12 Meta pixels per pageload is counted
  // as one offending vendor, not twelve separate findings.
  const pixelRequests = network.requests.filter((r) => r.is_tracking_pixel);
  const pixelDomains = Array.from(
    new Set(pixelRequests.map((r) => r.registered_domain || r.domain))
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("flow.title")}</CardTitle>
        <CardDescription>{t("flow.desc", { count: sorted.length })}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {pixelDomains.length > 0 && (
          <Alert className="border-risk-high/40 bg-risk-high/5">
            <Radar className="h-4 w-4 text-risk-high" />
            <AlertTitle className="text-sm">
              {t("flow.pixels.title", { count: pixelRequests.length })}
            </AlertTitle>
            <AlertDescription className="text-xs">
              <div className="mb-1">{t("flow.pixels.desc")}</div>
              <div className="font-mono text-[11px] text-muted-foreground">
                {pixelDomains.join(" · ")}
              </div>
            </AlertDescription>
          </Alert>
        )}
        {sorted.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("flow.empty")}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="py-2 pr-3">{t("flow.h.domain")}</th>
                  <th className="py-2 pr-3">{t("flow.h.country")}</th>
                  <th className="py-2 pr-3">{t("flow.h.risk")}</th>
                  <th className="py-2 pr-3">{t("flow.h.categories")}</th>
                  <th className="py-2 pr-3 text-right">{t("flow.h.requests")}</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((d) => (
                  <tr key={d.domain} className="border-b last:border-b-0">
                    <td className="py-2 pr-3 font-mono text-xs">{d.domain}</td>
                    <td className="py-2 pr-3">
                      <Badge className={countryColor(d.country)}>{d.country}</Badge>
                    </td>
                    <td className="py-2 pr-3">
                      <Badge className={severityColor(d.risk)}>{d.risk}</Badge>
                    </td>
                    <td className="py-2 pr-3 text-xs text-muted-foreground">
                      {d.categories.length ? d.categories.join(", ") : "—"}
                    </td>
                    <td className="py-2 pr-3 text-right font-mono text-xs">{d.request_count}</td>
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
