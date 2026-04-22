"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { countryColor, severityColor } from "@/lib/utils";
import { useLang } from "@/lib/LanguageContext";
import type { DataFlowEntry } from "@/lib/types";

export function DataFlowTable({ flow }: { flow: DataFlowEntry[] }) {
  const { t } = useLang();
  const sorted = [...flow].sort((a, b) => {
    const order = { high: 0, medium: 1, low: 2 } as const;
    return order[a.risk] - order[b.risk] || b.request_count - a.request_count;
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("flow.title")}</CardTitle>
        <CardDescription>{t("flow.desc", { count: sorted.length })}</CardDescription>
      </CardHeader>
      <CardContent>
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
