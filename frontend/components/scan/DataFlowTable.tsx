import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { countryColor, severityColor } from "@/lib/utils";
import type { DataFlowEntry } from "@/lib/types";

export function DataFlowTable({ flow }: { flow: DataFlowEntry[] }) {
  const sorted = [...flow].sort((a, b) => {
    const order = { high: 0, medium: 1, low: 2 } as const;
    return order[a.risk] - order[b.risk] || b.request_count - a.request_count;
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>Data flow</CardTitle>
        <CardDescription>
          Third-party domains the site contacted ({sorted.length} unique).
        </CardDescription>
      </CardHeader>
      <CardContent>
        {sorted.length === 0 ? (
          <p className="text-sm text-muted-foreground">No third-party requests observed.</p>
        ) : (
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
                {sorted.map((d) => (
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
        )}
      </CardContent>
    </Card>
  );
}
