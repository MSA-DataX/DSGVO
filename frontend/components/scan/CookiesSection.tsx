"use client";

import * as React from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { categoryColor } from "@/lib/utils";
import type { CookieReport } from "@/lib/types";

export function CookiesSection({ report }: { report: CookieReport }) {
  const s = report.summary;
  const totals = [
    ["Necessary", s.cookies_necessary ?? 0, "necessary"],
    ["Functional", s.cookies_functional ?? 0, "functional"],
    ["Analytics", s.cookies_analytics ?? 0, "analytics"],
    ["Marketing", s.cookies_marketing ?? 0, "marketing"],
    ["Unknown", s.cookies_unknown ?? 0, "unknown"],
  ] as const;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Cookies & Web Storage</CardTitle>
        <CardDescription>
          {s.total_cookies ?? 0} cookies ({s.third_party_cookies ?? 0} third-party,{" "}
          {s.session_cookies ?? 0} session-only) · {s.total_storage ?? 0} storage entries
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="mb-4 flex flex-wrap gap-2">
          {totals.map(([label, count, key]) => (
            <Badge key={key} className={categoryColor(key as any)}>
              {label}: {count}
            </Badge>
          ))}
        </div>

        <Tabs defaultValue="cookies">
          <TabsList>
            <TabsTrigger value="cookies">Cookies ({report.cookies.length})</TabsTrigger>
            <TabsTrigger value="storage">Storage ({report.storage.length})</TabsTrigger>
          </TabsList>

          <TabsContent value="cookies">
            <CookieTable rows={report.cookies} />
          </TabsContent>
          <TabsContent value="storage">
            <StorageTable rows={report.storage} />
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}

function CookieTable({ rows }: { rows: CookieReport["cookies"] }) {
  if (rows.length === 0) return <Empty />;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
            <th className="py-2 pr-3">Name</th>
            <th className="py-2 pr-3">Domain</th>
            <th className="py-2 pr-3">Category</th>
            <th className="py-2 pr-3">Vendor</th>
            <th className="py-2 pr-3">Reason</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((c, i) => (
            <tr key={i} className="border-b last:border-b-0 align-top">
              <td className="py-2 pr-3 font-mono text-xs">{c.name}</td>
              <td className="py-2 pr-3 font-mono text-xs">
                {c.domain}{" "}
                {c.is_third_party && (
                  <Badge variant="outline" className="ml-1 text-[10px]">3rd-party</Badge>
                )}
              </td>
              <td className="py-2 pr-3">
                <Badge className={categoryColor(c.category)}>{c.category}</Badge>
              </td>
              <td className="py-2 pr-3 text-xs">{c.vendor ?? "—"}</td>
              <td className="py-2 pr-3 text-xs text-muted-foreground">{c.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StorageTable({ rows }: { rows: CookieReport["storage"] }) {
  if (rows.length === 0) return <Empty />;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
            <th className="py-2 pr-3">Key</th>
            <th className="py-2 pr-3">Kind</th>
            <th className="py-2 pr-3">Category</th>
            <th className="py-2 pr-3">Vendor</th>
            <th className="py-2 pr-3">Reason</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s, i) => (
            <tr key={i} className="border-b last:border-b-0 align-top">
              <td className="py-2 pr-3 font-mono text-xs">{s.key}</td>
              <td className="py-2 pr-3 text-xs">{s.kind}</td>
              <td className="py-2 pr-3">
                <Badge className={categoryColor(s.category)}>{s.category}</Badge>
              </td>
              <td className="py-2 pr-3 text-xs">{s.vendor ?? "—"}</td>
              <td className="py-2 pr-3 text-xs text-muted-foreground">{s.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Empty() {
  return <p className="py-3 text-sm text-muted-foreground">Nothing to show.</p>;
}
