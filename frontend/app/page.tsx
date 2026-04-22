"use client";

import * as React from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
import { PrivacyAnalysisCard } from "@/components/scan/PrivacyAnalysisCard";
import { FormsSection } from "@/components/scan/FormsSection";
import { getScan, streamScan } from "@/lib/api";
import type { ProgressEvent, ScanResponse } from "@/lib/types";

export default function Home() {
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
      await streamScan(
        { url, ...opts },
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
        <div className="sm:text-right">
          <h1 className="text-xl font-semibold">GDPR Compliance Scanner</h1>
          <p className="text-sm text-muted-foreground">
            Crawler · network capture · cookie analysis · AI privacy review · risk score.
          </p>
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
          <AlertTitle>Scan failed</AlertTitle>
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
  );
}

function Results({ result }: { result: ScanResponse }) {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="text-xs text-muted-foreground">
          {result.id && <>Scan <code className="font-mono">{result.id}</code>{" · "}</>}
          {result.created_at && new Date(result.created_at).toLocaleString()}
        </div>
        <ExportButton result={result} />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <RiskScoreCard risk={result.risk} target={result.target} />
        </div>
        <SubScoresCard subScores={result.risk.sub_scores} />
      </div>

      <HardCapsList caps={result.risk.applied_caps} />

      {result.consent && <ConsentSection consent={result.consent} />}

      <RecommendationsList recs={result.risk.recommendations} />

      <div className="grid gap-6 lg:grid-cols-2">
        <DataFlowTable flow={result.network.data_flow} />
        <CookiesSection report={result.cookies} />
      </div>

      <ContactChannelsSection report={result.contact_channels} />

      <ThirdPartyWidgetsSection report={result.widgets} />

      <FirstPartyScriptsSection network={result.network} />

      <PrivacyAnalysisCard analysis={result.privacy_analysis} />

      <FormsSection report={result.forms} />
    </div>
  );
}
