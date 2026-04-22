"use client";

import * as React from "react";
import { ChevronDown, ChevronRight, FileCode } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useLang } from "@/lib/LanguageContext";
import type { NetworkResult } from "@/lib/types";

// Aggregates first-party script/stylesheet loads so the operator can
// eyeball which of their own assets run. Closes the "the other tool
// flagged my own cookie-consent.js as a beacon" gap by making the full
// first-party surface visible instead of implicit.

type Group = {
  url: string;
  resource_type: string;
  request_count: number;
};

const INTERESTING_TYPES = new Set(["script", "stylesheet", "xhr", "fetch"]);

function aggregate(network: NetworkResult): Group[] {
  const by_url = new Map<string, Group>();
  for (const r of network.requests) {
    if (r.is_third_party) continue;
    const t = (r.resource_type ?? "").toLowerCase();
    if (!INTERESTING_TYPES.has(t)) continue;
    // Normalize: strip query strings and hashes so /main.js?v=123 and
    // /main.js?v=124 count as one row. Actual duplication is visible
    // in request_count.
    const clean = r.url.split("?")[0].split("#")[0];
    const key = `${t}:${clean}`;
    const prev = by_url.get(key);
    if (prev) prev.request_count += 1;
    else by_url.set(key, { url: clean, resource_type: t, request_count: 1 });
  }
  return [...by_url.values()].sort((a, b) =>
    a.resource_type === b.resource_type
      ? b.request_count - a.request_count
      : a.resource_type.localeCompare(b.resource_type),
  );
}

const TYPE_STYLE: Record<string, string> = {
  script:     "bg-violet-500/10 text-violet-700 dark:text-violet-400",
  stylesheet: "bg-sky-500/10 text-sky-700 dark:text-sky-400",
  xhr:        "bg-amber-500/10 text-amber-700 dark:text-amber-400",
  fetch:      "bg-amber-500/10 text-amber-700 dark:text-amber-400",
};

export function FirstPartyScriptsSection({ network }: { network: NetworkResult }) {
  const { t } = useLang();
  const [open, setOpen] = React.useState(false);
  const groups = React.useMemo(() => aggregate(network), [network]);

  if (groups.length === 0) return null;

  const scripts = groups.filter((g) => g.resource_type === "script").length;
  const styles = groups.filter((g) => g.resource_type === "stylesheet").length;
  const apis = groups.filter((g) => g.resource_type === "xhr" || g.resource_type === "fetch").length;

  return (
    <Card>
      <CardHeader>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex w-full items-start justify-between gap-3 text-left"
        >
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <FileCode className="h-4 w-4" />
              {t("firstParty.title")}
            </CardTitle>
            <CardDescription>
              {t("firstParty.desc", { count: groups.length, scripts, styles, apis })}
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
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="py-2 pr-3">{t("firstParty.h.type")}</th>
                  <th className="py-2 pr-3">{t("firstParty.h.url")}</th>
                  <th className="py-2 pr-3 text-right">{t("firstParty.h.requests")}</th>
                </tr>
              </thead>
              <tbody>
                {groups.map((g, i) => (
                  <tr key={i} className="border-b last:border-b-0">
                    <td className="py-2 pr-3">
                      <Badge className={`text-[10px] uppercase ${TYPE_STYLE[g.resource_type] ?? ""}`}>
                        {g.resource_type}
                      </Badge>
                    </td>
                    <td className="break-all py-2 pr-3 font-mono text-xs">
                      <a href={g.url} target="_blank" rel="noreferrer" className="hover:underline">
                        {g.url}
                      </a>
                    </td>
                    <td className="py-2 pr-3 text-right font-mono text-xs">{g.request_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      )}
    </Card>
  );
}
