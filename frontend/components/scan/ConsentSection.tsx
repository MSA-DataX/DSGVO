import { CheckCircle2, AlertTriangle, MousePointerClick, Info, ShieldAlert, ShieldCheck } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { categoryColor, countryColor, severityColor } from "@/lib/utils";
import type { ConsentSimulation, ConsentUxAudit, DarkPatternCode } from "@/lib/types";

const DARK_PATTERN_LABEL: Record<DarkPatternCode, string> = {
  no_direct_reject:         "No first-level Reject button",
  reject_via_text_fallback: "Reject matched via loose text heuristic",
  reject_much_smaller:      "Reject button significantly smaller than Accept",
  reject_below_fold:        "Reject button below the viewport",
  reject_low_prominence:    "Reject styled less prominently",
  forced_interaction:       "Banner blocks content without opt-out",
};

export function ConsentSection({ consent }: { consent: ConsentSimulation }) {
  const diff = consent.diff;
  const noDiff =
    diff &&
    diff.new_cookies.length === 0 &&
    diff.new_storage.length === 0 &&
    diff.new_data_flow.length === 0 &&
    diff.extra_request_count === 0;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2">
              <MousePointerClick className="h-5 w-5" /> Consent simulation
            </CardTitle>
            <CardDescription>{consent.note}</CardDescription>
          </div>
          {consent.cmp_detected && (
            <Badge variant="outline" className="font-mono text-[10px] uppercase">
              {consent.cmp_detected}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {consent.ux_audit && <UxAuditBlock audit={consent.ux_audit} />}

        {!consent.accept_clicked && (
          <Alert>
            <Info className="h-4 w-4" />
            <AlertTitle>No banner clicked</AlertTitle>
            <AlertDescription>
              Either the site has no cookie banner, or our detection didn't recognize it. The pre/post
              diff below is unlikely to be meaningful.
            </AlertDescription>
          </Alert>
        )}

        {diff && noDiff && consent.accept_clicked && (
          <Alert>
            <CheckCircle2 className="h-4 w-4 text-risk-low" />
            <AlertTitle>No additional tracking after consent</AlertTitle>
            <AlertDescription>
              Clicking “Accept all” triggered no new cookies, storage entries, or third-party
              requests. Either the site does no tracking, or it was already loading everything
              pre-consent (which would be a separate finding).
            </AlertDescription>
          </Alert>
        )}

        {diff && !noDiff && (
          <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Stat label="New cookies" value={diff.new_cookies.length} />
              <Stat label="New storage" value={diff.new_storage.length} />
              <Stat label="New domains" value={diff.new_data_flow.length} />
              <Stat label="Extra requests" value={diff.extra_request_count} />
            </div>

            {(diff.new_marketing_count > 0 || diff.new_analytics_count > 0) && (
              <Alert variant="destructive">
                <AlertTriangle className="h-4 w-4" />
                <AlertTitle>Trackers correctly gated behind consent</AlertTitle>
                <AlertDescription>
                  After consent, the site loaded {diff.new_marketing_count} marketing and{" "}
                  {diff.new_analytics_count} analytics tracker(s) that were not present before.
                  This is the *correct* behavior — but ensure the privacy policy lists each
                  recipient and the consent banner offers granular per-category opt-in.
                </AlertDescription>
              </Alert>
            )}

            {diff.new_data_flow.length > 0 && (
              <div>
                <div className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
                  New third-party domains
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
                        <th className="py-2 pr-3">Domain</th>
                        <th className="py-2 pr-3">Country</th>
                        <th className="py-2 pr-3">Risk</th>
                        <th className="py-2 pr-3">Categories</th>
                        <th className="py-2 pr-3 text-right">Requests</th>
                      </tr>
                    </thead>
                    <tbody>
                      {diff.new_data_flow.map((d) => (
                        <tr key={d.domain} className="border-b last:border-b-0">
                          <td className="py-2 pr-3 font-mono text-xs">{d.domain}</td>
                          <td className="py-2 pr-3">
                            <Badge className={countryColor(d.country)}>{d.country}</Badge>
                          </td>
                          <td className="py-2 pr-3">
                            <Badge className={severityColor(d.risk)}>{d.risk}</Badge>
                          </td>
                          <td className="py-2 pr-3 text-xs text-muted-foreground">
                            {d.categories.length ? d.categories.join(", ") : "—"}
                          </td>
                          <td className="py-2 pr-3 text-right font-mono text-xs">{d.request_count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {diff.new_cookies.length > 0 && (
              <div>
                <div className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
                  New cookies
                </div>
                <ul className="flex flex-wrap gap-1.5">
                  {diff.new_cookies.map((c, i) => (
                    <li key={i}>
                      <Badge className={categoryColor(c.category)} title={c.reason}>
                        <span className="font-mono text-[10px]">{c.name}</span>
                        <span className="ml-1 opacity-70">@{c.domain}</span>
                      </Badge>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {diff.new_storage.length > 0 && (
              <div>
                <div className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
                  New web-storage entries
                </div>
                <ul className="flex flex-wrap gap-1.5">
                  {diff.new_storage.map((s, i) => (
                    <li key={i}>
                      <Badge className={categoryColor(s.category)} title={s.reason}>
                        <span className="font-mono text-[10px]">{s.key}</span>
                        <span className="ml-1 opacity-70">({s.kind})</span>
                      </Badge>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}

        <div className="grid grid-cols-2 gap-3 border-t pt-3 text-xs text-muted-foreground">
          <div>
            <div className="font-medium text-foreground">Pre-consent</div>
            <div>{consent.pre_summary.total_cookies ?? 0} cookies · {consent.pre_summary.total_storage ?? 0} storage</div>
          </div>
          <div>
            <div className="font-medium text-foreground">Post-consent</div>
            <div>{consent.post_summary.total_cookies ?? 0} cookies · {consent.post_summary.total_storage ?? 0} storage</div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border p-3">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
    </div>
  );
}

// -- Consent UX / Dark-pattern audit (Phase 3) ----------------------------

function UxAuditBlock({ audit }: { audit: ConsentUxAudit }) {
  if (!audit.banner_detected) {
    return null; // No findings to show when there was no banner to measure
  }

  const findings = audit.findings;
  if (findings.length === 0) {
    return (
      <Alert>
        <ShieldCheck className="h-4 w-4 text-risk-low" />
        <AlertTitle>Consent banner UX looks clean</AlertTitle>
        <AlertDescription>
          Accept and Reject buttons are present at the same level, comparable in size and
          prominence. No dark patterns detected.
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="rounded-md border border-risk-high/40 bg-risk-high/5">
      <div className="flex items-center gap-2 border-b border-risk-high/30 p-3">
        <ShieldAlert className="h-4 w-4 text-risk-high" />
        <div className="text-sm font-medium text-risk-high">
          Consent banner dark patterns ({findings.length})
        </div>
      </div>
      <ul className="divide-y">
        {findings.map((f, i) => (
          <li key={i} className="space-y-1 p-3">
            <div className="flex items-center gap-2">
              <Badge className={`text-[10px] ${severityColor(f.severity)}`}>
                {f.severity}
              </Badge>
              <span className="text-sm font-medium">
                {DARK_PATTERN_LABEL[f.code] ?? f.code}
              </span>
            </div>
            <p className="text-xs text-muted-foreground">{f.description}</p>
            {Object.keys(f.evidence).length > 0 && (
              <div className="flex flex-wrap gap-1 pt-1">
                {Object.entries(f.evidence).map(([k, v]) => (
                  <code
                    key={k}
                    className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-mono"
                  >
                    {k}: {String(v)}
                  </code>
                ))}
              </div>
            )}
          </li>
        ))}
      </ul>
      {audit.accept_metrics && audit.reject_metrics && (
        <div className="grid grid-cols-2 gap-3 border-t border-risk-high/30 p-3 text-[11px] text-muted-foreground">
          <div>
            <div className="font-medium text-foreground">Accept button</div>
            <div>
              {Math.round(Number(audit.accept_metrics["width"]) || 0)}×
              {Math.round(Number(audit.accept_metrics["height"]) || 0)} px ·{" "}
              weight {Number(audit.accept_metrics["fontWeight"]) || 400} ·{" "}
              {audit.accept_metrics["hasOwnBackground"] ? "filled" : "plain"}
            </div>
          </div>
          <div>
            <div className="font-medium text-foreground">Reject button</div>
            <div>
              {Math.round(Number(audit.reject_metrics["width"]) || 0)}×
              {Math.round(Number(audit.reject_metrics["height"]) || 0)} px ·{" "}
              weight {Number(audit.reject_metrics["fontWeight"]) || 400} ·{" "}
              {audit.reject_metrics["hasOwnBackground"] ? "filled" : "plain"}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
