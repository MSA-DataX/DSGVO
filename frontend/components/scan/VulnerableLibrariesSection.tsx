"use client";

import { AlertTriangle, Package } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { severityColor } from "@/lib/utils";
import { useLang } from "@/lib/LanguageContext";
import type { VulnerableLibrariesReport } from "@/lib/types";

// Retire.js-style findings. Rendered as a dedicated card because the
// data shape (library + version + CVE list + fix-version) deserves its
// own table; squeezing it into the security audit section would be too
// dense.

export function VulnerableLibrariesSection({
  report,
}: {
  report: VulnerableLibrariesReport;
}) {
  const { t } = useLang();
  if (!report || report.libraries.length === 0) return null;

  const s = report.summary;
  const titleColor = (s.high ?? 0) > 0 ? "text-risk-high" : "text-risk-medium";

  return (
    <Card>
      <CardHeader>
        <CardTitle className={`flex items-center gap-2 ${titleColor}`}>
          {(s.high ?? 0) > 0 ? (
            <AlertTriangle className="h-5 w-5" />
          ) : (
            <Package className="h-5 w-5" />
          )}
          {t("vulnLibs.title")}
        </CardTitle>
        <CardDescription>
          {t("vulnLibs.desc", {
            total: s.total ?? report.libraries.length,
            high: s.high ?? 0,
            medium: s.medium ?? 0,
            low: s.low ?? 0,
          })}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th className="py-2 pr-3">{t("vulnLibs.h.lib")}</th>
                <th className="py-2 pr-3">{t("vulnLibs.h.version")}</th>
                <th className="py-2 pr-3">{t("vulnLibs.h.severity")}</th>
                <th className="py-2 pr-3">{t("vulnLibs.h.fixed")}</th>
                <th className="py-2 pr-3">{t("vulnLibs.h.cves")}</th>
                <th className="py-2 pr-3">{t("vulnLibs.h.advisory")}</th>
              </tr>
            </thead>
            <tbody>
              {report.libraries.map((v, i) => (
                <tr key={i} className="border-b last:border-b-0 align-top">
                  <td className="py-2 pr-3 font-mono text-xs">{v.library}</td>
                  <td className="py-2 pr-3 font-mono text-xs">{v.detected_version}</td>
                  <td className="py-2 pr-3">
                    <Badge className={severityColor(v.severity)}>
                      {t(`severity.${v.severity}`)}
                    </Badge>
                  </td>
                  <td className="py-2 pr-3 font-mono text-xs text-muted-foreground">
                    {v.fixed_in ?? "—"}
                  </td>
                  <td className="py-2 pr-3">
                    <div className="flex flex-wrap gap-1">
                      {v.cves.map((cve) => (
                        <a
                          key={cve}
                          href={`https://nvd.nist.gov/vuln/detail/${cve}`}
                          target="_blank"
                          rel="noreferrer"
                          className="font-mono text-[11px] underline hover:text-primary"
                        >
                          {cve}
                        </a>
                      ))}
                      {v.cves.length === 0 && <span className="text-xs text-muted-foreground">—</span>}
                    </div>
                  </td>
                  <td className="py-2 pr-3 text-xs text-muted-foreground">{v.advisory}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
