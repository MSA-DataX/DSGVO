"use client";

import * as React from "react";
import { Check, X, Info, ExternalLink, Copy, AlertTriangle, ClipboardCheck } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { severityColor } from "@/lib/utils";
import { useLang } from "@/lib/LanguageContext";
import type { Lang } from "@/lib/i18n";
import type { DsarCheck, DsarRight, PolicyIssue, PrivacyAnalysis } from "@/lib/types";

const COVERAGE_LABELS: Record<Lang, Record<string, string>> = {
  en: {
    legal_basis_stated: "Art. 6 legal basis stated",
    data_categories_listed: "Data categories listed",
    retention_period_stated: "Retention period stated",
    third_party_recipients_listed: "Third-party recipients listed",
    third_country_transfers_disclosed: "Third-country transfers disclosed",
    user_rights_enumerated: "User rights (Art. 15–22) enumerated",
    contact_for_data_protection: "Contact for data protection",
    cookie_section_present: "Cookie section present",
    children_data_addressed: "Children's data addressed",
  },
  de: {
    legal_basis_stated: "Rechtsgrundlage (Art. 6) genannt",
    data_categories_listed: "Datenkategorien aufgeführt",
    retention_period_stated: "Speicherdauer angegeben",
    third_party_recipients_listed: "Drittempfänger aufgeführt",
    third_country_transfers_disclosed: "Drittland-Übermittlungen offengelegt",
    user_rights_enumerated: "Betroffenenrechte (Art. 15–22) aufgezählt",
    contact_for_data_protection: "Datenschutz-Kontakt angegeben",
    cookie_section_present: "Cookie-Abschnitt vorhanden",
    children_data_addressed: "Daten von Kindern adressiert",
  },
};

const ISSUE_LABEL: Record<Lang, Record<string, string>> = {
  en: {
    missing_section: "Missing section",
    unclear_wording: "Unclear wording",
    risky_processing: "Risky processing",
    third_country_transfer: "Third-country transfer",
    missing_user_rights: "Missing user rights",
    missing_legal_basis: "Missing legal basis",
    missing_retention: "Missing retention",
    missing_dpo: "Missing DPO",
    other: "Other",
  },
  de: {
    missing_section: "Fehlender Abschnitt",
    unclear_wording: "Unklare Formulierung",
    risky_processing: "Risikobehaftete Verarbeitung",
    third_country_transfer: "Drittland-Übermittlung",
    missing_user_rights: "Fehlende Nutzerrechte",
    missing_legal_basis: "Fehlende Rechtsgrundlage",
    missing_retention: "Fehlende Speicherdauer",
    missing_dpo: "Fehlender Datenschutzbeauftragter",
    other: "Sonstiges",
  },
};

export function PrivacyAnalysisCard({ analysis }: { analysis: PrivacyAnalysis }) {
  const { t, lang } = useLang();
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <CardTitle>{t("privacy.title")}</CardTitle>
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
                t("privacy.noPolicy")
              )}
            </CardDescription>
          </div>
          <div className="text-right">
            <div className="text-3xl font-bold">{analysis.compliance_score}<span className="text-sm font-normal text-muted-foreground">/100</span></div>
            <div className="mt-1 text-xs text-muted-foreground">
              {analysis.provider === "none"
                ? t("privacy.noAi")
                : `${analysis.provider}${analysis.model ? ` · ${analysis.model}` : ""}`}
            </div>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {analysis.error && (
          <Alert>
            <Info className="h-4 w-4" />
            <AlertTitle>{t("privacy.aiFailedTitle")}</AlertTitle>
            <AlertDescription>
              <code className="text-xs">{analysis.error}</code>
              {analysis.error === "no_provider_configured" && (
                <p className="mt-1">
                  {lang === "de"
                    ? <><code>OPENAI_API_KEY</code> oder die Azure-OpenAI-Variablen in <code>backend/.env</code> setzen und erneut scannen, um die Policy-Analyse zu aktivieren.</>
                    : <>Set <code>OPENAI_API_KEY</code> or the Azure OpenAI variables in <code>backend/.env</code> and re-scan to enable policy analysis.</>}
                </p>
              )}
            </AlertDescription>
          </Alert>
        )}

        {analysis.summary && (
          <div>
            <div className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">{t("privacy.summary")}</div>
            <p className="text-sm leading-relaxed">{analysis.summary}</p>
          </div>
        )}

        {analysis.coverage && (
          <div>
            <div className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">{t("privacy.coverage")}</div>
            <ul className="grid grid-cols-1 gap-1 sm:grid-cols-2">
              {Object.entries(analysis.coverage).map(([k, v]) => (
                <li key={k} className="flex items-center gap-2 text-sm">
                  {v ? (
                    <Check className="h-4 w-4 text-risk-low" />
                  ) : (
                    <X className="h-4 w-4 text-risk-high" />
                  )}
                  <span className={v ? "" : "text-muted-foreground"}>{COVERAGE_LABELS[lang][k] ?? k}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {analysis.dsar && <DsarBlock dsar={analysis.dsar} />}

        {analysis.issues.length > 0 && (
          <div>
            <div className="mb-2 text-xs uppercase tracking-wide text-muted-foreground">
              {t("privacy.issues", { count: analysis.issues.length })}
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
            {t("privacy.charsSent", { chars: analysis.excerpt_chars_sent.toLocaleString() })}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

// -- Per-issue card, with optional auto-fix draft -------------------------

function IssueCard({ issue }: { issue: PolicyIssue }) {
  const { t, lang } = useLang();
  const steps = issue.action_steps ?? [];
  return (
    <li className="rounded-md border p-3">
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <Badge className={severityColor(issue.severity)}>{t(`severity.${issue.severity}`)}</Badge>
        <span className="text-sm font-medium">{ISSUE_LABEL[lang][issue.category] ?? issue.category}</span>
        {typeof issue.risk_score === "number" && (
          <span className="ml-auto text-[11px] font-mono text-muted-foreground">
            {t("privacy.risk", { score: issue.risk_score })}
          </span>
        )}
      </div>
      <p className="text-sm">{issue.description}</p>
      {issue.excerpt && (
        <blockquote className="mt-2 border-l-2 pl-3 text-xs italic text-muted-foreground">
          “{issue.excerpt}”
        </blockquote>
      )}
      {steps.length > 0 && (
        <div className="mt-3">
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            {t("privacy.steps.title")}
          </div>
          <ol className="list-inside list-decimal space-y-0.5 text-xs">
            {steps.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ol>
        </div>
      )}
      {issue.suggested_text && <SuggestedTextBlock text={issue.suggested_text} />}
      {issue.suggested_code && <SuggestedCodeBlock code={issue.suggested_code} />}
      {issue.monitoring_trigger && (
        <p className="mt-3 flex items-start gap-1.5 text-[11px] text-muted-foreground">
          <Info className="mt-0.5 h-3 w-3 shrink-0" />
          <span>{t("privacy.monitor", { trigger: issue.monitoring_trigger })}</span>
        </p>
      )}
    </li>
  );
}

// Pure code snippet (nginx directive, HTML fragment, JS). Different
// styling from SuggestedTextBlock because this block is language-
// agnostic — no legal disclaimer needed, since it's a technical fix,
// not a policy text draft the user would paste into a legal document.
function SuggestedCodeBlock({ code }: { code: string }) {
  const { t } = useLang();
  const [copied, setCopied] = React.useState(false);
  const [open, setOpen] = React.useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard denied (iframe / insecure context) — user can still select manually
    }
  }

  return (
    <div className="mt-3 rounded-md border border-sky-500/40 bg-sky-500/5">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs"
      >
        <span className="flex items-center gap-2 font-medium text-sky-700 dark:text-sky-400">
          <Copy className="h-3.5 w-3.5" />
          {t("privacy.code.title")}
        </span>
        <span className="text-muted-foreground">
          {open ? t("privacy.draft.hide") : t("privacy.draft.show")}
        </span>
      </button>
      {open && (
        <div className="border-t border-sky-500/30 px-3 py-3">
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded bg-background p-3 font-mono text-[11px] leading-relaxed">
            {code}
          </pre>
          <div className="mt-2 flex justify-end">
            <Button variant="outline" size="sm" onClick={copy}>
              {copied ? (
                <><ClipboardCheck className="mr-2 h-4 w-4" /> {t("privacy.draft.copied")}</>
              ) : (
                <><Copy className="mr-2 h-4 w-4" /> {t("privacy.code.copy")}</>
              )}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function SuggestedTextBlock({ text }: { text: string }) {
  const { t } = useLang();
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
          {t("privacy.draft.title")}
        </span>
        <span className="text-muted-foreground">{open ? t("privacy.draft.hide") : t("privacy.draft.show")}</span>
      </button>
      {open && (
        <div className="border-t border-amber-500/30 px-3 py-3">
          <Alert className="mb-3 border-amber-500/40 bg-amber-500/10">
            <Info className="h-4 w-4" />
            <AlertTitle className="text-xs">{t("privacy.draft.disclaimerTitle")}</AlertTitle>
            <AlertDescription className="text-xs">
              {t("privacy.draft.disclaimerBody")}
            </AlertDescription>
          </Alert>
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded bg-background p-3 text-xs leading-relaxed">
            {text}
          </pre>
          <div className="mt-2 flex justify-end">
            <Button variant="outline" size="sm" onClick={copy}>
              {copied ? (
                <><ClipboardCheck className="mr-2 h-4 w-4" /> {t("privacy.draft.copied")}</>
              ) : (
                <><Copy className="mr-2 h-4 w-4" /> {t("privacy.draft.copy")}</>
              )}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

// -- DSAR / Art. 13(2)(b) deterministic check ----------------------------
//
// Mirrors backend/app/modules/dsar_detector.py output. The detector runs
// even when the AI provider is `none`, so this block is the only privacy
// signal a no-key install ever shows. Score-driven tone: ≥80 green,
// ≥40 amber, <40 red.

const DSAR_RIGHT_LABEL: Record<Lang, Record<DsarRight, string>> = {
  en: {
    access: "Right of access (Art. 15)",
    rectification: "Right to rectification (Art. 16)",
    erasure: "Right to erasure (Art. 17)",
    restriction: "Right to restriction (Art. 18)",
    portability: "Right to portability (Art. 20)",
    objection: "Right to object (Art. 21)",
    complaint: "Right to complain to a DPA (Art. 77)",
    withdraw_consent: "Right to withdraw consent (Art. 7(3))",
  },
  de: {
    access: "Auskunftsrecht (Art. 15)",
    rectification: "Recht auf Berichtigung (Art. 16)",
    erasure: "Recht auf Löschung (Art. 17)",
    restriction: "Recht auf Einschränkung (Art. 18)",
    portability: "Recht auf Datenübertragbarkeit (Art. 20)",
    objection: "Widerspruchsrecht (Art. 21)",
    complaint: "Beschwerderecht bei der Aufsichtsbehörde (Art. 77)",
    withdraw_consent: "Widerruf der Einwilligung (Art. 7(3))",
  },
};

const ALL_DSAR_RIGHTS: DsarRight[] = [
  "access",
  "rectification",
  "erasure",
  "restriction",
  "portability",
  "objection",
  "complaint",
  "withdraw_consent",
];

function DsarBlock({ dsar }: { dsar: DsarCheck }) {
  const { t, lang } = useLang();
  const named = new Set(dsar.named_rights);
  const score = dsar.score;
  const tone =
    score >= 80
      ? "text-risk-low"
      : score >= 40
      ? "text-risk-medium"
      : "text-risk-high";
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <div className="text-xs uppercase tracking-wide text-muted-foreground">
          {t("privacy.dsar.title")}
        </div>
        <div className={`text-xs font-mono ${tone}`}>
          {t("privacy.dsar.score", { score, total: ALL_DSAR_RIGHTS.length })}
        </div>
      </div>
      <ul className="grid grid-cols-1 gap-1 sm:grid-cols-2">
        {ALL_DSAR_RIGHTS.map((r) => {
          const present = named.has(r);
          return (
            <li key={r} className="flex items-center gap-2 text-sm">
              {present ? (
                <Check className="h-4 w-4 text-risk-low" />
              ) : (
                <X className="h-4 w-4 text-risk-high" />
              )}
              <span className={present ? "" : "text-muted-foreground"}>
                {DSAR_RIGHT_LABEL[lang][r]}
              </span>
            </li>
          );
        })}
        <li className="flex items-center gap-2 text-sm sm:col-span-2">
          {dsar.has_rights_contact ? (
            <Check className="h-4 w-4 text-risk-low" />
          ) : (
            <X className="h-4 w-4 text-risk-high" />
          )}
          <span className={dsar.has_rights_contact ? "" : "text-muted-foreground"}>
            {t("privacy.dsar.contact")}
          </span>
        </li>
      </ul>
      {dsar.contact_excerpt && (
        <blockquote className="mt-2 border-l-2 pl-3 text-xs italic text-muted-foreground">
          “{dsar.contact_excerpt}”
        </blockquote>
      )}
    </div>
  );
}
