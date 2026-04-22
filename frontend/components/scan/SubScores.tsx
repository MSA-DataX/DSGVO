import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type { SubScore } from "@/lib/types";

const NICE_NAME: Record<string, string> = {
  cookies: "Cookies",
  tracking: "Tracking & web storage",
  data_transfer: "Data transfer",
  privacy: "Privacy policy",
  forms: "Forms",
};

function indicatorFor(score: number): string {
  if (score >= 80) return "bg-risk-low";
  if (score >= 60) return "bg-risk-medium";
  if (score >= 40) return "bg-risk-high";
  return "bg-risk-critical";
}

export function SubScoresCard({ subScores }: { subScores: SubScore[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Sub-scores</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {subScores.map((s) => (
          <div key={s.name}>
            <div className="mb-1 flex items-baseline justify-between">
              <span className="text-sm font-medium">{NICE_NAME[s.name] ?? s.name}</span>
              <span className="text-xs text-muted-foreground">
                weight {Math.round(s.weight * 100)}% · contributes {s.weighted_contribution.toFixed(1)}
              </span>
            </div>
            <div className="flex items-center gap-3">
              <Progress value={s.score} indicatorClassName={indicatorFor(s.score)} className="flex-1" />
              <span className="w-12 text-right font-mono text-sm">{s.score}</span>
            </div>
            {s.notes.length > 0 && (
              <ul className="mt-1 list-inside list-disc text-xs text-muted-foreground">
                {s.notes.map((n, i) => (
                  <li key={i}>{n}</li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
