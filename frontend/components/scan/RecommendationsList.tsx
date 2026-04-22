"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { severityColor } from "@/lib/utils";
import { useLang } from "@/lib/LanguageContext";
import type { Recommendation } from "@/lib/types";

export function RecommendationsList({ recs }: { recs: Recommendation[] }) {
  const { t } = useLang();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("recs.title")}</CardTitle>
      </CardHeader>
      <CardContent>
        {recs.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("recs.empty")}</p>
        ) : (
          <ol className="space-y-3">
            {recs.map((r, i) => (
              <li key={i} className="rounded-md border p-3">
                <div className="flex items-start gap-3">
                  <Badge className={severityColor(r.priority)}>{t(`recs.priority.${r.priority}`)}</Badge>
                  <div className="flex-1">
                    <div className="font-medium">{r.title}</div>
                    <p className="mt-1 text-sm text-muted-foreground">{r.detail}</p>
                    {r.related.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {r.related.slice(0, 6).map((rel) => (
                          <code key={rel} className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">
                            {rel}
                          </code>
                        ))}
                        {r.related.length > 6 && (
                          <span className="text-xs text-muted-foreground">
                            +{r.related.length - 6} more
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}
