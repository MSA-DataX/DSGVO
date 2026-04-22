"use client";

import * as React from "react";
import { Check, X, Info, ExternalLink, Copy, AlertTriangle, ClipboardCheck } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { severityColor } from "@/lib/utils";
import type { PolicyIssue, PrivacyAnalysis } from "@/lib/types";

const COVERAGE_LABELS: Record<string, string> = {
  legal_basis_stated: "Art. 6 legal basis stated",
  data_categories_listed: "Data categories listed",
  retention_period_stated: "Retention period stated",
  third_party_recipients_listed: "Third-party recipients listed",
  third_country_transfers_disclosed: "Third-country transfers disclosed",
  user_rights_enumerated: "User rights (Art. 15–22) enumerated",
  contact_for_data_protection: "Contact for data protection",
  cookie_section_present: "Cookie section present",
  children_data_addressed: "Children's data addressed",
};

const ISSUE_LABEL: Record<string, string> = {
  missing_section: "Missing section",
  unclear_wording: "Unclear wording",
  risky_processing: "Risky processing",
  third_country_transfer: "Third-country transfer",
  missing_user_rights: "Missing user rights",
  missing_legal_basis: "Missing legal basis",
  missing_retention: "Missing retention",
  missing_dpo: "Missing DPO",
  other: "Other",
};

export function PrivacyAnalysisCard({ analysis }: { analysis: PrivacyAnalysis }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <CardTitle>Privacy policy analysis</CardTitle>
            <CardDescription>
              {analysis.policy_url ? (
                <a
                  href={analysis.policy_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 underline"
                >
                  {analysis.policy_url}
                  <ExternalLink className="h-3 w-3" />
                </a>
              ) : (
                "No privacy policy was located."
              )}
            </CardDescription>
          </div>
          <div className="text-right">
            <div className="text-3xl font-bold">{analysis.compliance_score}<span className="text-sm font-normal text-muted-foreground">/100</span></div>
            <div className="mt-1 text-xs text-muted-foreground">
              {analysis.provider === "none"
                ? "no AI provider"
                : `${analysis.provider}${analysis.model ? ` · ${analysis.model}` : ""}`}
            </div>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {analysis.error && (
          <Alert>
            <Info className="h-4 w-4" />
            <AlertTitle>AI analysis incomplete</AlertTitle>
            <AlertDescription>
              <code className="text-xs">{analysis.error}</code>
              {analysis.error === "no_provider_configured" && (
                <p className="mt-1">
                  Set <code>OPENAI_API_KEY</code> or the Azure OpenAI variables in <code>backend/.env</code> and
                  re-scan to enable policy analysis.
                </p>
              )}
            </AlertDescription>
          </Alert>
        )}

        {analysis.summary && (
          <div>
            <div className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">Summary</div>
            <p className="text-sm leading-relaxed">{analysis.summary}</p>
          </div>
        )}

        {analysis.coverage && (
          <div>
            <div className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">Required GDPR sections</div>
            <ul className="grid grid-cols-1 gap-1 sm:grid-cols-2">
              {Object.entries(analysis.coverage).map(([k, v]) => (
                <li key={k} className="flex items-center gap-2 text-sm">
                  {v ? (
                    <Check className="h-4 w-4 text-risk-low" />
                  ) : (
                    <X className="h-4 w-4 text-risk-high" />
                  )}
                  <span className={v ? "" : "text-muted-foreground"}>{COVERAGE_LABELS[k] ?? k}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {analysis.issues.length > 0 && (
          <div>
            <div className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
              Issues ({analysis.issues.length})
            </div>
            <ul className="space-y-2">
              {analysis.issues.map((iss, i) => (
                <IssueCard key={i} issue={iss} />
              ))}
            </ul>
          </div>
        )}

        {analysis.excerpt_chars_sent > 0 && (
          <p className="text-xs text-muted-foreground">
            Sent {analysis.excerpt_chars_sent.toLocaleString()} chars of policy text to the model.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

// -- Per-issue card, with optional auto-fix draft -------------------------

function IssueCard({ issue }: { issue: PolicyIssue }) {
  return (
    <li className="rounded-md border p-3">
      <div className="mb-1 flex items-center gap-2">
        <Badge className={severityColor(issue.severity)}>{issue.severity}</Badge>
        <span className="text-sm font-medium">{ISSUE_LABEL[issue.category] ?? issue.category}</span>
      </div>
      <p className="text-sm">{issue.description}</p>
      {issue.excerpt && (
        <blockquote className="mt-2 border-l-2 pl-3 text-xs italic text-muted-foreground">
          “{issue.excerpt}”
        </blockquote>
      )}
      {issue.suggested_text && <SuggestedTextBlock text={issue.suggested_text} />}
    </li>
  );
}

function SuggestedTextBlock({ text }: { text: string }) {
  const [copied, setCopied] = React.useState(false);
  const [open, setOpen] = React.useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard API failed (iframe, insecure context); fall back to select
    }
  }

  return (
    <div className="mt-3 rounded-md border border-amber-500/40 bg-amber-500/5">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs"
      >
        <span className="flex items-center gap-2 font-medium text-amber-800 dark:text-amber-400">
          <AlertTriangle className="h-3.5 w-3.5" />
          Draft policy text — legal review required
        </span>
        <span className="text-muted-foreground">{open ? "hide" : "show"}</span>
      </button>
      {open && (
        <div className="border-t border-amber-500/30 px-3 py-3">
          <Alert className="mb-3 border-amber-500/40 bg-amber-500/10">
            <Info className="h-4 w-4" />
            <AlertTitle className="text-xs">This is an AI-generated draft, not legal advice.</AlertTitle>
            <AlertDescription className="text-xs">
              The text below is a starting point to close the finding above. It must be reviewed
              and adapted by qualified legal counsel before being published. MSA DataX does not
              guarantee legal sufficiency and assumes no liability for its use.
            </AlertDescription>
          </Alert>
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded bg-background p-3 text-xs leading-relaxed">
            {text}
          </pre>
          <div className="mt-2 flex justify-end">
            <Button variant="outline" size="sm" onClick={copy}>
              {copied ? (
                <><ClipboardCheck className="mr-2 h-4 w-4" /> Copied</>
              ) : (
                <><Copy className="mr-2 h-4 w-4" /> Copy draft</>
              )}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
