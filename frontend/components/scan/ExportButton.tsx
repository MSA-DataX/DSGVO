"use client";

import * as React from "react";
import { Download, FileText, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useLang } from "@/lib/LanguageContext";
import type { ScanResponse } from "@/lib/types";

// PDF renderer is ~450 KB — dynamic-imported only when the user actually
// clicks Export PDF, so the initial bundle stays small.

function safeSlug(url: string): string {
  return url.replace(/^https?:\/\//, "").replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "").toLowerCase();
}

export function ExportButton({ result }: { result: ScanResponse }) {
  const { t, lang } = useLang();
  const [pdfLoading, setPdfLoading] = React.useState(false);

  function downloadJson() {
    const blob = new Blob([JSON.stringify(result, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const ts = (result.created_at ?? new Date().toISOString()).replace(/[:T]/g, "-").slice(0, 19);
    a.href = url;
    a.download = `gdpr-scan-${safeSlug(result.target)}-${ts}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  async function downloadPdf() {
    setPdfLoading(true);
    try {
      const { generateAndDownloadPdf } = await import("./PdfReport");
      await generateAndDownloadPdf(result, lang);
    } catch (e) {
      // fall back to JSON if the PDF lib fails to load (rare, mostly SSR edge)
      // eslint-disable-next-line no-console
      console.error("PDF export failed", e);
      downloadJson();
    } finally {
      setPdfLoading(false);
    }
  }

  return (
    <div className="flex gap-2">
      <Button variant="outline" size="sm" onClick={downloadPdf} disabled={pdfLoading}>
        {pdfLoading ? (
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        ) : (
          <FileText className="mr-2 h-4 w-4" />
        )}
        {pdfLoading ? t("export.generating") : t("export.pdf")}
      </Button>
      <Button variant="outline" size="sm" onClick={downloadJson}>
        <Download className="mr-2 h-4 w-4" />
        {t("export.json")}
      </Button>
    </div>
  );
}
