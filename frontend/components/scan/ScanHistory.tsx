"use client";

import * as React from "react";
import { History, Trash2, RefreshCcw, Loader2 } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { deleteScan, listScans } from "@/lib/api";
import { ratingBg } from "@/lib/utils";
import { useLang } from "@/lib/LanguageContext";
import type { ScanListItem } from "@/lib/types";

function formatWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

export function ScanHistory({
  onLoad,
  activeId,
}: {
  onLoad: (id: string) => void;
  activeId?: string | null;
}) {
  const { t } = useLang();
  const [items, setItems] = React.useState<ScanListItem[] | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setItems(await listScans(25));
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void refresh();
  }, [refresh]);

  async function handleDelete(id: string) {
    try {
      await deleteScan(id);
      await refresh();
    } catch (e: any) {
      setError(e?.message ?? String(e));
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-3">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            <History className="h-4 w-4" /> {t("history.title")}
          </CardTitle>
          <CardDescription>
            {items ? t("history.count", { count: items.length }) : t("history.loading")}
          </CardDescription>
        </div>
        <Button variant="ghost" size="sm" onClick={refresh} disabled={loading}>
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
        </Button>
      </CardHeader>
      <CardContent>
        {error && <p className="text-sm text-risk-high">{error}</p>}
        {items && items.length === 0 && (
          <p className="text-sm text-muted-foreground">{t("history.empty")}</p>
        )}
        <ul className="divide-y">
          {items?.map((s) => (
            <li
              key={s.id}
              className={`flex items-center gap-3 py-2 ${s.id === activeId ? "bg-muted/50 -mx-3 px-3 rounded" : ""}`}
            >
              <button
                onClick={() => onLoad(s.id)}
                className="flex flex-1 items-center gap-3 text-left hover:underline"
              >
                <span className={`inline-flex w-12 justify-center rounded px-2 py-0.5 text-xs font-mono ${ratingBg(s.rating)}`}>
                  {s.score}
                </span>
                <span className="flex-1 truncate text-sm">{s.url}</span>
                <Badge className={`${ratingBg(s.rating)} text-[10px] uppercase`}>{s.rating}</Badge>
                <span className="hidden text-xs text-muted-foreground md:inline">
                  {formatWhen(s.created_at)}
                </span>
              </button>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={() => handleDelete(s.id)}
                aria-label="delete"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
