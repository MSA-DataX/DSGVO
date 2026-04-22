import { AlertTriangle } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { HardCap } from "@/lib/types";

export function HardCapsList({ caps }: { caps: HardCap[] }) {
  if (caps.length === 0) return null;
  return (
    <Card className="border-risk-high">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-risk-high">
          <AlertTriangle className="h-5 w-5" /> Hard caps applied
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {caps.map((c) => (
          <Alert key={c.code} variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertTitle className="font-mono text-xs uppercase tracking-wide">
              {c.code} · max score {c.cap_value}
            </AlertTitle>
            <AlertDescription>{c.description}</AlertDescription>
          </Alert>
        ))}
      </CardContent>
    </Card>
  );
}
