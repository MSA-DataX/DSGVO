import { CheckCircle2, AlertTriangle, MousePointerClick, Info } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { categoryColor, countryColor, severityColor } from "@/lib/utils";
import type { ConsentSimulation } from "@/lib/types";

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
