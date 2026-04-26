"use client";

import * as React from "react";
import { Search, Loader2, ChevronDown, ChevronRight, Globe } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useLang } from "@/lib/LanguageContext";

export function ScanForm({
  onSubmit,
  loading,
}: {
  onSubmit: (
    url: string,
    opts: {
      max_depth: number;
      max_pages: number;
      consent_simulation: boolean;
      privacy_policy_url?: string;
      performance_audit: boolean;
    },
  ) => void;
  loading: boolean;
}) {
  const { t } = useLang();
  const [url, setUrl] = React.useState("");
  const [depth, setDepth] = React.useState(1);
  const [pages, setPages] = React.useState(5);
  const [consentSim, setConsentSim] = React.useState(false);
  const [perfAudit, setPerfAudit] = React.useState(false);
  const [privacyUrl, setPrivacyUrl] = React.useState("");
  const [advancedOpen, setAdvancedOpen] = React.useState(false);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    let cleaned = url.trim();
    if (!cleaned) return;
    if (!/^https?:\/\//i.test(cleaned)) cleaned = "https://" + cleaned;

    let p = privacyUrl.trim();
    if (p && !/^https?:\/\//i.test(p)) p = "https://" + p;

    onSubmit(cleaned, {
      max_depth: depth,
      max_pages: pages,
      consent_simulation: consentSim,
      privacy_policy_url: p || undefined,
      performance_audit: perfAudit,
    });
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-end">
        <div className="flex-1">
          <label className="mb-1.5 block text-xs font-medium text-muted-foreground">{t("form.url")}</label>
          {/* Prominenter URL-Input — h-14, größere Schrift, Globe-Icon
              links als Mini-Affordance "das hier kommt eine URL rein". */}
          <div className="relative">
            <Globe className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.com"
              disabled={loading}
              required
              className="h-12 pl-9 text-base"
            />
          </div>
        </div>
        <div className="flex gap-3">
          <div>
            <label className="mb-1.5 block text-xs font-medium text-muted-foreground">{t("form.depth")}</label>
            <Input
              type="number" min={0} max={3}
              value={depth}
              onChange={(e) => setDepth(parseInt(e.target.value || "0", 10))}
              disabled={loading} className="h-12 w-20"
            />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium text-muted-foreground">{t("form.maxPages")}</label>
            <Input
              type="number" min={1} max={25}
              value={pages}
              onChange={(e) => setPages(parseInt(e.target.value || "1", 10))}
              disabled={loading} className="h-12 w-24"
            />
          </div>
        </div>
        <Button type="submit" disabled={loading || !url.trim()} size="lg" className="h-12">
          {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Search className="mr-2 h-4 w-4" />}
          {loading ? t("form.scanning") : t("form.scan")}
        </Button>
      </div>

      <label className="flex items-center gap-2 text-sm text-muted-foreground">
        <input
          type="checkbox"
          checked={consentSim}
          onChange={(e) => setConsentSim(e.target.checked)}
          disabled={loading}
          className="h-4 w-4"
        />
        <span>
          <strong className="text-foreground">{t("form.consentSim.title")}</strong> — {t("form.consentSim.desc")}
        </span>
      </label>

      <label className="flex items-center gap-2 text-sm text-muted-foreground">
        <input
          type="checkbox"
          checked={perfAudit}
          onChange={(e) => setPerfAudit(e.target.checked)}
          disabled={loading}
          className="h-4 w-4"
        />
        <span>
          <strong className="text-foreground">{t("form.perfAudit.title")}</strong> — {t("form.perfAudit.desc")}
        </span>
      </label>

      {/* Advanced options collapsed by default — the URL override is the
          escape hatch for sites where BFS crawl + common-path probing both
          fail to find the privacy policy. */}
      <div>
        <button
          type="button"
          onClick={() => setAdvancedOpen((o) => !o)}
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        >
          {advancedOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          {t("form.advanced")}
        </button>
        {advancedOpen && (
          <div className="mt-2 rounded-md border p-3">
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              {t("form.privacyUrl.label")}
            </label>
            <Input
              value={privacyUrl}
              onChange={(e) => setPrivacyUrl(e.target.value)}
              placeholder="https://example.com/datenschutz"
              disabled={loading}
            />
            <p className="mt-1 text-xs text-muted-foreground">{t("form.privacyUrl.hint")}</p>
          </div>
        )}
      </div>
    </form>
  );
}
