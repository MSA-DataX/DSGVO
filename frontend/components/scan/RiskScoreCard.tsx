import { ShieldAlert, ShieldCheck } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { ratingBg, ratingColor } from "@/lib/utils";
import type { RiskScore } from "@/lib/types";

const RATING_LABEL: Record<RiskScore["rating"], string> = {
  low: "Low risk",
  medium: "Medium risk",
  high: "High risk",
  critical: "Critical risk",
};

const INDICATOR_BG: Record<RiskScore["rating"], string> = {
  low: "bg-risk-low",
  medium: "bg-risk-medium",
  high: "bg-risk-high",
  critical: "bg-risk-critical",
};

export function RiskScoreCard({ risk, target }: { risk: RiskScore; target: string }) {
  const Icon = risk.rating === "low" ? ShieldCheck : ShieldAlert;
  const capped = risk.weighted_score !== risk.score;

  return (
    <Card className={`border-2 ${ratingColor(risk.rating)}`}>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-4">
          <div>
            <CardDescription className="text-xs uppercase tracking-wide">GDPR risk score</CardDescription>
            <CardTitle className="break-all text-base font-medium">{target}</CardTitle>
          </div>
          <Icon className={`h-8 w-8 ${ratingColor(risk.rating).split(" ")[0]}`} />
        </div>
      </CardHeader>
      <CardContent>
        <div className="flex items-end gap-3">
          <span className={`text-6xl font-bold leading-none ${ratingColor(risk.rating).split(" ")[0]}`}>
            {risk.score}
          </span>
          <span className="pb-1 text-sm text-muted-foreground">/ 100</span>
          <Badge className={`ml-auto ${ratingBg(risk.rating)}`}>{RATING_LABEL[risk.rating]}</Badge>
        </div>
        <Progress value={risk.score} className="mt-4" indicatorClassName={INDICATOR_BG[risk.rating]} />
        {capped && (
          <p className="mt-3 text-xs text-muted-foreground">
            Weighted sub-score average was <strong>{risk.weighted_score}</strong> — final score capped by{" "}
            {risk.applied_caps.length} hard cap{risk.applied_caps.length === 1 ? "" : "s"}.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
