"use client";

import { AlertTriangle } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useLang } from "@/lib/LanguageContext";
import type { HardCap } from "@/lib/types";

export function HardCapsList({ caps }: { caps: HardCap[] }) {
  const { t } = useLang();
  if (caps.length === 0) return null;
  return (
    <Card className="border-risk-high">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-risk-high">
          <AlertTriangle className="h-5 w-5" /> {t("caps.title")}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {caps.map((c) => (
          <Alert key={c.code} variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertTitle className="font-mono text-xs uppercase tracking-wide">
              {c.code} · {t("caps.maxScore", { value: c.cap_value })}
            </AlertTitle>
            <AlertDescription>
              {c.description}
              {/* Affected sub-scores — small badge row showing which
                  sub-scores this cap is rooted in. Empty for cross-
                  cutting caps (typically security caps like
                  no_https_enforcement). */}
              {c.affected_subscores && c.affected_subscores.length > 0 && (
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    {t("caps.affects")}:
                  </span>
                  {c.affected_subscores.map((sub) => (
                    <Badge
                      key={sub}
                      className="bg-risk-high/15 text-risk-high text-[10px] font-mono"
                    >
                      {t(`sub.name.${sub}`)}
                    </Badge>
                  ))}
                </div>
              )}
            </AlertDescription>
          </Alert>
        ))}
      </CardContent>
    </Card>
  );
}
