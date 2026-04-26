"use client";

import * as React from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { categoryColor } from "@/lib/utils";
import { useLang } from "@/lib/LanguageContext";
import type { CookieCategory, CookieReport } from "@/lib/types";

// The cookie-scanner emits a per-row `reason` string for audit
// transparency. When no classification rule matched, the fallback
// reads like debug output ("no matching name or domain rule") and
// repeats on every row — visual noise. We strip those known
// boilerplate strings to a clean dash; meaningful reasons still
// surface verbatim (e.g. "matched _ga vendor pattern").
const _BOILERPLATE_REASON_PATTERNS: RegExp[] = [
  /no matching .* rule/i,
  /^unclassified$/i,
  /^unknown$/i,
];

function cleanReason(s: string | null | undefined): string | null {
  if (!s) return null;
  if (_BOILERPLATE_REASON_PATTERNS.some((rx) => rx.test(s))) return null;
  return s;
}

export function CookiesSection({ report }: { report: CookieReport }) {
  const { t } = useLang();
  const s = report.summary;
  const totals: [string, number, CookieCategory][] = [
    [t("category.necessary"),  s.cookies_necessary  ?? 0, "necessary"],
    [t("category.functional"), s.cookies_functional ?? 0, "functional"],
    [t("category.analytics"),  s.cookies_analytics  ?? 0, "analytics"],
    [t("category.marketing"),  s.cookies_marketing  ?? 0, "marketing"],
    [t("category.unknown"),    s.cookies_unknown    ?? 0, "unknown"],
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("cookies.title")}</CardTitle>
        <CardDescription>
          {t("cookies.desc", {
            total: s.total_cookies ?? 0,
            thirdParty: s.third_party_cookies ?? 0,
            session: s.session_cookies ?? 0,
            storage: s.total_storage ?? 0,
          })}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {/* Kategorie-Pills: Kategorien mit Count 0 werden visuell
            zurückgenommen (gedimmtes Outline-Badge) statt voll-bunt
            zu erscheinen. So zieht das Auge sofort auf die echten
            Werte; die "leeren" Kategorien sind als Kontext da, ohne
            zu konkurrieren. Convention #-design-polish. */}
        <div className="mb-4 flex flex-wrap gap-2">
          {totals.map(([label, count, key]) =>
            count > 0 ? (
              <Badge key={key} className={categoryColor(key)}>
                {label}: {count}
              </Badge>
            ) : (
              <Badge
                key={key}
                variant="outline"
                className="text-[11px] text-muted-foreground"
              >
                {label}: 0
              </Badge>
            ),
          )}
        </div>

        <Tabs defaultValue="cookies">
          <TabsList>
            <TabsTrigger value="cookies">{t("cookies.tab.cookies")} ({report.cookies.length})</TabsTrigger>
            <TabsTrigger value="storage">{t("cookies.tab.storage")} ({report.storage.length})</TabsTrigger>
          </TabsList>

          <TabsContent value="cookies">
            <CookieTable rows={report.cookies} />
          </TabsContent>
          <TabsContent value="storage">
            <StorageTable rows={report.storage} />
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}

function CookieTable({ rows }: { rows: CookieReport["cookies"] }) {
  const { t } = useLang();
  if (rows.length === 0) return <Empty />;
  // Spalten dynamisch: ANBIETER wird ganz weggelassen wenn KEIN Cookie
  // einen Vendor hat — sonst wäre es 14× "—" auf der Seite.
  // GRUND-Texte werden vor dem Render durch cleanReason gefiltert; eine
  // Zeile ohne sinnvolle Reason zeigt "—" statt Debug-Output.
  const showVendor = rows.some((c) => !!c.vendor);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
            <th className="py-2 pr-3">{t("cookies.h.name")}</th>
            <th className="py-2 pr-3">{t("cookies.h.domain")}</th>
            <th className="py-2 pr-3">{t("cookies.h.category")}</th>
            {showVendor && <th className="py-2 pr-3">{t("cookies.h.vendor")}</th>}
            <th className="py-2 pr-3">{t("cookies.h.reason")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c, i) => {
            const reason = cleanReason(c.reason);
            return (
              <tr key={i} className="border-b last:border-b-0 align-top">
                <td className="py-2 pr-3 font-mono text-xs">{c.name}</td>
                <td className="py-2 pr-3 font-mono text-xs">
                  {c.domain}{" "}
                  {c.is_third_party && (
                    <Badge variant="outline" className="ml-1 text-[10px]">{t("cookies.thirdParty")}</Badge>
                  )}
                </td>
                <td className="py-2 pr-3">
                  <Badge className={categoryColor(c.category)}>{t(`category.${c.category}`)}</Badge>
                </td>
                {showVendor && (
                  <td className="py-2 pr-3 text-xs">{c.vendor ?? "—"}</td>
                )}
                <td className="py-2 pr-3 text-xs text-muted-foreground">
                  {reason ?? <span className="text-muted-foreground/50">—</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function StorageTable({ rows }: { rows: CookieReport["storage"] }) {
  const { t } = useLang();
  if (rows.length === 0) return <Empty />;
  const showVendor = rows.some((r) => !!r.vendor);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
            <th className="py-2 pr-3">{t("cookies.h.key")}</th>
            <th className="py-2 pr-3">{t("cookies.h.kind")}</th>
            <th className="py-2 pr-3">{t("cookies.h.category")}</th>
            {showVendor && <th className="py-2 pr-3">{t("cookies.h.vendor")}</th>}
            <th className="py-2 pr-3">{t("cookies.h.reason")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s, i) => {
            const reason = cleanReason(s.reason);
            return (
              <tr key={i} className="border-b last:border-b-0 align-top">
                <td className="py-2 pr-3 font-mono text-xs">{s.key}</td>
                <td className="py-2 pr-3 text-xs">{s.kind}</td>
                <td className="py-2 pr-3">
                  <Badge className={categoryColor(s.category)}>{t(`category.${s.category}`)}</Badge>
                </td>
                {showVendor && (
                  <td className="py-2 pr-3 text-xs">{s.vendor ?? "—"}</td>
                )}
                <td className="py-2 pr-3 text-xs text-muted-foreground">
                  {reason ?? <span className="text-muted-foreground/50">—</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Empty() {
  const { t } = useLang();
  return <p className="py-3 text-sm text-muted-foreground">{t("cookies.empty")}</p>;
}
