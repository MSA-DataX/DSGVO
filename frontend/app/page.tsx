"use client";

import * as React from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { RequireAuth } from "@/components/auth/RequireAuth";
import { UserMenu } from "@/components/auth/UserMenu";
import { useLang } from "@/lib/LanguageContext";
import { Card, CardContent } from "@/components/ui/card";
import { ScanForm } from "@/components/scan/ScanForm";
import { ScanProgress } from "@/components/scan/ScanProgress";
import { ScanHistory } from "@/components/scan/ScanHistory";
import { ExportButton } from "@/components/scan/ExportButton";
import { ConsentSection } from "@/components/scan/ConsentSection";
import { RiskScoreCard } from "@/components/scan/RiskScoreCard";
import { SubScoresCard } from "@/components/scan/SubScores";
import { HardCapsList } from "@/components/scan/HardCapsList";
import { RecommendationsList } from "@/components/scan/RecommendationsList";
import { DataFlowTable } from "@/components/scan/DataFlowTable";
import { CookiesSection } from "@/components/scan/CookiesSection";
import { FirstPartyScriptsSection } from "@/components/scan/FirstPartyScriptsSection";
import { ContactChannelsSection } from "@/components/scan/ContactChannelsSection";
import { ThirdPartyWidgetsSection } from "@/components/scan/ThirdPartyWidgetsSection";
import { SecurityAuditSection } from "@/components/scan/SecurityAuditSection";
import { VulnerableLibrariesSection } from "@/components/scan/VulnerableLibrariesSection";
import { PrivacyAnalysisCard } from "@/components/scan/PrivacyAnalysisCard";
import { FormsSection } from "@/components/scan/FormsSection";
import { ChapterHeader } from "@/components/scan/ChapterHeader";
import { getScan, streamScanAuto } from "@/lib/api";
import type { ProgressEvent, ScanResponse } from "@/lib/types";

export default function Home() {
  const { t, lang } = useLang();
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [result, setResult] = React.useState<ScanResponse | null>(null);
  const [events, setEvents] = React.useState<ProgressEvent[]>([]);
  const [historyNonce, setHistoryNonce] = React.useState(0);  // refresh signal

  // Used to cancel the in-flight stream if the user starts a new scan.
  const abortRef = React.useRef<AbortController | null>(null);

  async function onScan(
    url: string,
    opts: {
      max_depth: number;
      max_pages: number;
      consent_simulation: boolean;
      privacy_policy_url?: string;
    },
  ) {
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;

    setLoading(true);
    setError(null);
    setResult(null);
    setEvents([]);

    try {
      await streamScanAuto(
        { url, ...opts, ui_language: lang },
        {
          onProgress: (ev) => setEvents((prev) => [...prev, ev]),
          onResult: (r) => {
            setResult(r);
            setHistoryNonce((n) => n + 1);
          },
          onError: (err) => setError(err),
        },
        ac.signal,
      );
    } catch (e: any) {
      if (e?.name !== "AbortError") setError(e?.message ?? String(e));
    } finally {
      setLoading(false);
    }
  }

  async function loadFromHistory(id: string) {
    abortRef.current?.abort();
    setLoading(false);
    setError(null);
    setEvents([]);
    try {
      setResult(await getScan(id));
    } catch (e: any) {
      setError(e?.message ?? String(e));
    }
  }

  return (
    <RequireAuth>
    <main className="container mx-auto max-w-6xl py-8">
      <header className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        {/* Logo lives in public/logo.png (the dark banner artwork). Has its own
            background baked into the image, so it sits as a branded block next
            to the product title rather than bleeding into the page. */}
        <img
          src="/logo.png"
          alt="MSA DataX"
          className="h-12 w-auto rounded-md"
        />
        <div className="flex items-start gap-4 sm:text-right">
          <div className="flex-1">
            <h1 className="text-xl font-semibold">{t("app.title")}</h1>
            <p className="text-sm text-muted-foreground">{t("app.subtitle")}</p>
          </div>
          <LanguageSwitcher />
          <UserMenu />
        </div>
      </header>

      <Card className="mb-6">
        <CardContent className="pt-6">
          <ScanForm onSubmit={onScan} loading={loading} />
        </CardContent>
      </Card>

      {loading && <ScanProgress events={events} errored={false} />}

      {error && (
        <Alert variant="destructive" className="mb-6">
          <AlertTitle>{t("progress.failed")}</AlertTitle>
          <AlertDescription className="font-mono text-xs">{error}</AlertDescription>
        </Alert>
      )}

      {result && <Results result={result} />}

      <div className="mt-8">
        {/* Key forces refresh when a new scan is stored. */}
        <ScanHistory
          key={historyNonce}
          onLoad={loadFromHistory}
          activeId={result?.id ?? null}
        />
      </div>
    </main>
    </RequireAuth>
  );
}

function Results({ result }: { result: ScanResponse }) {
  const { t } = useLang();
  return (
    <div className="space-y-6">
      {/* -- Top strip: scan meta + jump nav + export --------------- */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-xs text-muted-foreground">
          {result.id && <>{t("common.scanId")} <code className="font-mono">{result.id}</code>{" · "}</>}
          {result.created_at && new Date(result.created_at).toLocaleString()}
        </div>
        <div className="flex items-center gap-3">
          <JumpNav />
          <ExportButton result={result} />
        </div>
      </div>

      {/* -- Overview (cross-cutting, no chapter header) ------------
          Score + sub-scores + hard caps + recommendations are
          audience-agnostic: legal, security and management all read
          these first. Everything below is grouped by audience. */}
      <div id="overview" className="scroll-mt-20 space-y-6">
        <div className="grid gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <RiskScoreCard risk={result.risk} target={result.target} />
          </div>
          <SubScoresCard subScores={result.risk.sub_scores} />
        </div>

        <HardCapsList caps={result.risk.applied_caps} />

        <RecommendationsList recs={result.risk.recommendations} />
      </div>

      {/* -- Chapter 1: GDPR / Privacy ------------------------------ */}
      <ChapterHeader
        id="chapter-privacy"
        number={1}
        titleKey="chapter.privacy.title"
        refKey="chapter.privacy.ref"
      />

      <PrivacyAnalysisCard analysis={result.privacy_analysis} />

      <div className="grid gap-6 lg:grid-cols-2">
        <CookiesSection report={result.cookies} />
        <DataFlowTable flow={result.network.data_flow} />
      </div>

      {result.consent && <ConsentSection consent={result.consent} />}

      <ContactChannelsSection report={result.contact_channels} />

      <ThirdPartyWidgetsSection report={result.widgets} />

      <FormsSection report={result.forms} />

      {/* -- Chapter 2: Security & Art. 32 GDPR (TOM) --------------- */}
      <ChapterHeader
        id="chapter-security"
        number={2}
        titleKey="chapter.security.title"
        refKey="chapter.security.ref"
      />

      {result.security && <SecurityAuditSection audit={result.security} />}

      {result.vulnerable_libraries && (
        <VulnerableLibrariesSection report={result.vulnerable_libraries} />
      )}

      <FirstPartyScriptsSection network={result.network} />
    </div>
  );
}

// Inline jump-nav shown in the results header strip. Anchors into the
// scroll-mt-20 targets above. Hidden on narrow screens where the scroll
// is short anyway and the chip row would wrap to two lines.
function JumpNav() {
  const { t } = useLang();
  const link = "rounded-md px-2.5 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground transition-colors";
  return (
    <nav className="hidden items-center gap-1 rounded-md border bg-muted/30 p-0.5 md:flex">
      <span className="px-2 text-[10px] uppercase tracking-wide text-muted-foreground">
        {t("nav.jumpTo")}
      </span>
      <a href="#overview"         className={link}>{t("nav.overview")}</a>
      <a href="#chapter-privacy"  className={link}>{t("nav.privacy")}</a>
      <a href="#chapter-security" className={link}>{t("nav.security")}</a>
    </nav>
  );
}
