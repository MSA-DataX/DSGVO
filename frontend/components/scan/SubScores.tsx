"use client";

import { AlertTriangle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { useLang } from "@/lib/LanguageContext";
import type { HardCap, SubScore } from "@/lib/types";

function indicatorFor(score: number): string {
  if (score >= 80) return "bg-risk-low";
  if (score >= 60) return "bg-risk-medium";
  if (score >= 40) return "bg-risk-high";
  return "bg-risk-critical";
}

export function SubScoresCard({
  subScores,
  caps = [],
}: {
  subScores: SubScore[];
  caps?: HardCap[];
}) {
  const { t } = useLang();
  // Pre-bucket caps per sub-score name once, so each row look-up is
  // O(1). Source of truth is the backend's `affected_subscores` field
  // (populated by scoring._CAP_AFFECTS). Multi-affected caps (e.g.
  // google_fonts_external → data_transfer + cookies) appear under
  // BOTH rows so the auditor can read the full causal chain from
  // either side.
  const capsBySub = caps.reduce<Record<string, HardCap[]>>((acc, c) => {
    for (const sub of c.affected_subscores ?? []) {
      (acc[sub] ??= []).push(c);
    }
    return acc;
  }, {});
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("sub.title")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {subScores.map((s) => {
          const rowCaps = capsBySub[s.name] ?? [];
          return (
            <div key={s.name}>
              <div className="mb-1 flex items-baseline justify-between gap-2">
                <span className="flex items-center gap-1.5 text-sm font-medium">
                  {t(`sub.name.${s.name}`)}
                  {rowCaps.length > 0 && (
                    <Badge
                      className="bg-risk-high/15 text-risk-high text-[10px] font-mono uppercase tracking-wide"
                      title={rowCaps.map((c) => `${c.code} → max ${c.cap_value}`).join(" · ")}
                    >
                      <AlertTriangle className="mr-1 h-3 w-3" />
                      {t("sub.cappedBy", { count: rowCaps.length })}
                    </Badge>
                  )}
                </span>
                <span className="text-xs text-muted-foreground">
                  {t("sub.weight", {
                    pct: Math.round(s.weight * 100),
                    value: s.weighted_contribution.toFixed(1),
                  })}
                </span>
              </div>
              <div className="flex items-center gap-3">
                <Progress value={s.score} indicatorClassName={indicatorFor(s.score)} className="flex-1" />
                <span className="w-12 text-right font-mono text-sm">{s.score}</span>
              </div>
              {s.notes.length > 0 && (
                <ul className="mt-1 list-inside list-disc text-xs text-muted-foreground">
                  {s.notes.map((n, i) => (
                    <li key={i}>{n}</li>
                  ))}
                </ul>
              )}
              {rowCaps.length > 0 && (
                <ul className="mt-1.5 space-y-0.5 text-[11px]">
                  {rowCaps.map((c) => (
                    <li key={c.code} className="font-mono text-risk-high">
                      ↳ {c.code} {t("sub.capValue", { value: c.cap_value })}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
