"use client";

import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ScanResponse } from "@/lib/types";

function safeSlug(url: string): string {
  return url.replace(/^https?:\/\//, "").replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "").toLowerCase();
}

export function ExportButton({ result }: { result: ScanResponse }) {
  function download() {
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

  return (
    <Button variant="outline" size="sm" onClick={download}>
      <Download className="mr-2 h-4 w-4" />
      Export JSON
    </Button>
  );
}
