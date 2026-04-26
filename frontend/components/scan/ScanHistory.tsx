"use client";

import * as React from "react";
import { History, Trash2, RefreshCcw, Loader2, Globe, MoreVertical } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { deleteScan, listScans } from "@/lib/api";
import { ratingBg } from "@/lib/utils";
import { useLang } from "@/lib/LanguageContext";
import type { ScanListItem } from "@/lib/types";

// History redesigned — Card-Stack statt nackter <ul>. Pro Eintrag:
// Favicon + zirkuläres Score-Badge + Domain (bold) / Pfad (muted) +
// Risk-Pill + relative Zeit + drei-Punkte-Menu.
//
// Favicon-Quelle bewusst direkt von der gescannten Domain, NICHT
// von google.com/s2/favicons — das wäre ein Drittland-Leak (Google
// erfährt jede Scan-Domain) und widerspricht Convention #7.
// Browser-`<img>`-Tag löst CORS-Issues nicht aus, das geht.
// onError-Fallback auf einen Globe-Icon falls die Domain kein
// /favicon.ico hat.

function formatRelative(iso: string, lang: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const diffMs = Date.now() - d.getTime();
  const sec = Math.floor(diffMs / 1000);
  const min = Math.floor(sec / 60);
  const hr = Math.floor(min / 60);
  const day = Math.floor(hr / 24);
  // We use Intl.RelativeTimeFormat — built-in, locale-aware, no deps.
  const rtf = new Intl.RelativeTimeFormat(lang, { numeric: "auto" });
  if (sec < 60) return rtf.format(-sec, "second");
  if (min < 60) return rtf.format(-min, "minute");
  if (hr < 24) return rtf.format(-hr, "hour");
  if (day < 30) return rtf.format(-day, "day");
  return d.toLocaleDateString(lang);
}

function splitDomainPath(rawUrl: string): { hostname: string; path: string } {
  try {
    const u = new URL(rawUrl);
    return { hostname: u.hostname, path: u.pathname === "/" ? "" : u.pathname };
  } catch {
    return { hostname: rawUrl, path: "" };
  }
}

export function ScanHistory({
  onLoad,
  activeId,
}: {
  onLoad: (id: string) => void;
  activeId?: string | null;
}) {
  const { t, lang } = useLang();
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
          <div className="rounded-md border border-dashed py-8 text-center">
            <p className="text-sm text-muted-foreground">{t("history.empty")}</p>
          </div>
        )}
        <ul className="space-y-2">
          {items?.map((s) => (
            <ScanRow
              key={s.id}
              item={s}
              active={s.id === activeId}
              lang={lang}
              onLoad={onLoad}
              onDelete={handleDelete}
            />
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function ScanRow({
  item, active, lang, onLoad, onDelete,
}: {
  item: ScanListItem;
  active: boolean;
  lang: string;
  onLoad: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const { t } = useLang();
  const [menuOpen, setMenuOpen] = React.useState(false);
  const menuRef = React.useRef<HTMLDivElement>(null);
  const { hostname, path } = splitDomainPath(item.url);

  React.useEffect(() => {
    if (!menuOpen) return;
    function onClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [menuOpen]);

  return (
    <li
      className={`group flex items-center gap-3 rounded-lg border p-3 transition-colors hover:border-primary/40 hover:bg-accent/40 ${active ? "border-primary/60 bg-primary/5" : ""}`}
    >
      <button
        type="button"
        onClick={() => onLoad(item.id)}
        className="flex flex-1 items-center gap-3 text-left"
        aria-label={`Open scan for ${hostname}`}
      >
        <Favicon hostname={hostname} />
        <CircularScore score={item.score} rating={item.rating} />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-1.5">
            <span className="truncate text-sm font-medium">{hostname}</span>
            {path && (
              <span className="truncate text-xs text-muted-foreground">{path}</span>
            )}
          </div>
          <div className="mt-0.5 text-xs text-muted-foreground">
            {formatRelative(item.created_at, lang)}
          </div>
        </div>
        <Badge className={`hidden uppercase tracking-wide sm:inline-flex ${ratingBg(item.rating)}`}>
          {item.rating}
        </Badge>
      </button>
      {/* Three-dot menu — keeps Delete out of the click-target so a
          mis-click on the row opens the report, never deletes a scan. */}
      <div ref={menuRef} className="relative">
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 opacity-0 transition-opacity group-hover:opacity-100 data-[state=open]:opacity-100"
          data-state={menuOpen ? "open" : "closed"}
          onClick={(e) => {
            e.stopPropagation();
            setMenuOpen((o) => !o);
          }}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
        >
          <MoreVertical className="h-4 w-4" />
        </Button>
        {menuOpen && (
          <div
            role="menu"
            className="absolute right-0 z-10 mt-1 w-40 overflow-hidden rounded-md border bg-card shadow-lg"
          >
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMenuOpen(false);
                onDelete(item.id);
              }}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-risk-high hover:bg-accent"
            >
              <Trash2 className="h-3.5 w-3.5" />
              {t("history.delete")}
            </button>
          </div>
        )}
      </div>
    </li>
  );
}

function Favicon({ hostname }: { hostname: string }) {
  const [errored, setErrored] = React.useState(false);
  if (errored || !hostname) {
    return (
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
        <Globe className="h-3.5 w-3.5" />
      </span>
    );
  }
  return (
    // Direkt von der gescannten Domain — keine Google-Favicon-API. Das
    // sendet die Domain-Liste der Org NICHT an einen Drittanbieter.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={`https://${hostname}/favicon.ico`}
      alt=""
      width={28}
      height={28}
      className="h-7 w-7 shrink-0 rounded-md border bg-background"
      onError={() => setErrored(true)}
      loading="lazy"
    />
  );
}

function CircularScore({ score, rating }: { score: number; rating: string }) {
  // Plain SVG ring, no extra deps. radius/stroke chosen so the 32px
  // outer dimension matches Favicon visually.
  const radius = 14;
  const stroke = 3;
  const circ = 2 * Math.PI * radius;
  const dash = (Math.max(0, Math.min(100, score)) / 100) * circ;
  const colorClass = ratingTextClass(rating);
  return (
    <div className="relative shrink-0" style={{ width: 36, height: 36 }}>
      <svg width="36" height="36" viewBox="0 0 36 36" className="-rotate-90">
        <circle
          cx="18" cy="18" r={radius}
          fill="none"
          stroke="currentColor"
          strokeOpacity="0.15"
          strokeWidth={stroke}
        />
        <circle
          cx="18" cy="18" r={radius}
          fill="none"
          className={colorClass}
          stroke="currentColor"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circ}`}
        />
      </svg>
      <span className={`absolute inset-0 flex items-center justify-center font-mono text-[11px] font-semibold ${colorClass}`}>
        {score}
      </span>
    </div>
  );
}

function ratingTextClass(rating: string): string {
  if (rating === "low") return "text-risk-low";
  if (rating === "medium") return "text-risk-medium";
  if (rating === "high") return "text-risk-high";
  return "text-risk-critical";
}
