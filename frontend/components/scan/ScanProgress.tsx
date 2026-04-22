"use client";

import { Check, Loader2, X } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { useLang } from "@/lib/LanguageContext";
import type { ProgressEvent, ProgressStage } from "@/lib/types";

// Ordered pipeline — drives the checklist UI. Must match scanner.py emits.
const STAGE_KEYS: { key: ProgressStage; tkey: string }[] = [
  { key: "started",            tkey: "progress.started" },
  { key: "crawling",           tkey: "progress.crawling" },
  { key: "cookie_analysis",    tkey: "progress.cookie" },
  { key: "policy_extraction",  tkey: "progress.policy" },
  { key: "ai_analysis",        tkey: "progress.ai" },
  { key: "form_analysis",      tkey: "progress.forms" },
  { key: "scoring",            tkey: "progress.scoring" },
];

export function ScanProgress({
  events,
  errored,
}: {
  events: ProgressEvent[];
  errored: boolean;
}) {
  const { t } = useLang();
  const latestByStage = new Map<ProgressStage, ProgressEvent>();
  for (const ev of events) latestByStage.set(ev.stage, ev);

  const reachedIdx = (() => {
    let i = -1;
    STAGE_KEYS.forEach((s, idx) => {
      if (latestByStage.has(s.key)) i = idx;
    });
    return i;
  })();

  const latestEvent = events[events.length - 1];

  return (
    <Card>
      <CardContent className="py-6">
        <div className="mb-4 flex items-center gap-3">
          {errored ? (
            <X className="h-5 w-5 text-risk-high" />
          ) : (
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          )}
          <div className="flex-1">
            <div className="text-sm font-medium">
              {errored ? t("progress.failed") : latestEvent?.message ?? t("progress.starting")}
            </div>
            {!errored && latestEvent?.data && Object.keys(latestEvent.data).length > 0 && (
              <div className="text-xs text-muted-foreground">
                {Object.entries(latestEvent.data)
                  .map(([k, v]) => `${k}: ${String(v)}`)
                  .join(" · ")}
              </div>
            )}
          </div>
        </div>

        <ul className="space-y-2">
          {STAGE_KEYS.map((s, idx) => {
            const reached = idx <= reachedIdx;
            const active = idx === reachedIdx && !errored;
            const ev = latestByStage.get(s.key);
            return (
              <li key={s.key} className="flex items-start gap-3">
                <StageIcon state={errored && active ? "error" : active ? "active" : reached ? "done" : "pending"} />
                <div className="flex-1">
                  <div className={cn(
                    "text-sm",
                    reached ? "font-medium" : "text-muted-foreground"
                  )}>
                    {t(s.tkey)}
                  </div>
                  {ev && (
                    <div className="text-xs text-muted-foreground">{ev.message}</div>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}

function StageIcon({ state }: { state: "pending" | "active" | "done" | "error" }) {
  if (state === "done") return <Check className="mt-0.5 h-4 w-4 text-risk-low" />;
  if (state === "active") return <Loader2 className="mt-0.5 h-4 w-4 animate-spin text-primary" />;
  if (state === "error") return <X className="mt-0.5 h-4 w-4 text-risk-high" />;
  return <span className="mt-1 inline-block h-3 w-3 rounded-full border border-muted-foreground/40" />;
}
