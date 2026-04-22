"use client";

import React from "react";
import {
  Document, Page, Text, View, StyleSheet, pdf,
} from "@react-pdf/renderer";
import type { ScanResponse } from "@/lib/types";
import { translate, type Lang } from "@/lib/i18n";

// @react-pdf/renderer is a separate React tree that renders to PDF via
// PDFKit under the hood. Styles are a subset of CSS — no flex gap, no
// calc(), no gradients. Layout is Flexbox-ish.
//
// Why client-side PDF generation: the raw ScanResponse is already in the
// browser, a second round-trip to the backend would duplicate rendering
// logic. Bundle size (~450 KB for react-pdf) is acceptable for an export
// feature that's only invoked on button click (dynamic import).

// ---------------------------------------------------------------------------
// Styles — shared + per-section
// ---------------------------------------------------------------------------

const COLORS = {
  low:      "#22c55e",
  medium:   "#f59e0b",
  high:     "#ea580c",
  critical: "#dc2626",
  muted:    "#6b7280",
  border:   "#e5e7eb",
  ink:      "#0f172a",
};

const styles = StyleSheet.create({
  page: {
    padding: 40,
    fontSize: 10,
    fontFamily: "Helvetica",
    color: COLORS.ink,
    lineHeight: 1.45,
  },
  h1: { fontSize: 22, fontWeight: 700, marginBottom: 4 },
  h2: { fontSize: 14, fontWeight: 700, marginTop: 14, marginBottom: 6,
        borderBottom: `1pt solid ${COLORS.border}`, paddingBottom: 3 },
  h3: { fontSize: 11, fontWeight: 700, marginTop: 8, marginBottom: 3 },
  muted:  { color: COLORS.muted, fontSize: 9 },
  small:  { fontSize: 8, color: COLORS.muted },
  row:    { flexDirection: "row" },
  col:    { flexDirection: "column" },
  tableHeader: {
    flexDirection: "row",
    borderBottom: `1pt solid ${COLORS.border}`,
    paddingBottom: 3,
    marginBottom: 3,
    fontSize: 8,
    fontWeight: 700,
    textTransform: "uppercase",
    color: COLORS.muted,
  },
  tableRow: {
    flexDirection: "row",
    borderBottom: `0.5pt solid ${COLORS.border}`,
    paddingVertical: 3,
  },
  cell: { paddingRight: 4 },
  badge: {
    borderRadius: 3,
    paddingHorizontal: 4,
    paddingVertical: 1,
    fontSize: 8,
    color: "#fff",
    alignSelf: "flex-start",
  },
  cover: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
  },
  coverLogo: {
    fontSize: 32, fontWeight: 700,
    color: "#06b6d4",
    marginBottom: 20,
    letterSpacing: 2,
  },
  coverScore: {
    fontSize: 96,
    fontWeight: 700,
    lineHeight: 1,
    marginVertical: 16,
  },
  coverUrl: {
    fontSize: 11,
    color: COLORS.muted,
    marginBottom: 24,
    textAlign: "center",
  },
  capBox: {
    borderLeft: `3pt solid ${COLORS.high}`,
    backgroundColor: "#fef3c7",
    padding: 8,
    marginBottom: 6,
  },
  recBox: {
    border: `0.5pt solid ${COLORS.border}`,
    padding: 8,
    marginBottom: 6,
  },
  footer: {
    position: "absolute",
    bottom: 20,
    left: 40,
    right: 40,
    fontSize: 7,
    color: COLORS.muted,
    textAlign: "center",
    borderTop: `0.5pt solid ${COLORS.border}`,
    paddingTop: 6,
  },
});

function ratingColor(rating: string): string {
  return (COLORS as Record<string, string>)[rating] ?? COLORS.muted;
}

function severityColor(s: string): string {
  return (COLORS as Record<string, string>)[s] ?? COLORS.muted;
}

// ---------------------------------------------------------------------------
// Small building blocks
// ---------------------------------------------------------------------------

function Badge({ children, color }: { children: React.ReactNode; color: string }) {
  return (
    <View style={[styles.badge, { backgroundColor: color }]}>
      <Text>{children}</Text>
    </View>
  );
}

function PageFooter({ lang }: { lang: Lang }) {
  return (
    <Text
      style={styles.footer}
      fixed
      render={({ pageNumber, totalPages }) =>
        `MSA DataX · ${translate(lang, "app.title")} · ${pageNumber}/${totalPages}`
      }
    />
  );
}

// ---------------------------------------------------------------------------
// Report body
// ---------------------------------------------------------------------------

function CoverPage({ result, lang, t }: { result: ScanResponse; lang: Lang; t: (k: string, v?: Record<string, string | number>) => string }) {
  return (
    <Page size="A4" style={styles.page}>
      <View style={styles.cover}>
        <Text style={styles.coverLogo}>MSA | DataX</Text>
        <Text style={{ fontSize: 18, fontWeight: 700 }}>{t("app.title")}</Text>
        <Text style={styles.coverUrl}>{result.target}</Text>

        <Text style={[styles.coverScore, { color: ratingColor(result.risk.rating) }]}>
          {result.risk.score}
        </Text>
        <Text style={{ fontSize: 12 }}>{t("risk.of100")}</Text>
        <View style={{ marginTop: 12 }}>
          <Badge color={ratingColor(result.risk.rating)}>
            {t(`risk.rating.${result.risk.rating}`)}
          </Badge>
        </View>

        <Text style={[styles.muted, { marginTop: 32 }]}>
          {result.created_at ? new Date(result.created_at).toLocaleString(lang) : new Date().toLocaleString(lang)}
        </Text>
        {result.id && <Text style={styles.small}>{t("common.scanId")} {result.id}</Text>}
      </View>
      <PageFooter lang={lang} />
    </Page>
  );
}

function SummaryPage({ result, lang, t }: { result: ScanResponse; lang: Lang; t: (k: string, v?: Record<string, string | number>) => string }) {
  const risk = result.risk;
  return (
    <Page size="A4" style={styles.page}>
      {/* Sub-scores table */}
      <Text style={styles.h2}>{t("sub.title")}</Text>
      <View style={styles.tableHeader}>
        <Text style={[styles.cell, { flex: 3 }]}>Category</Text>
        <Text style={[styles.cell, { flex: 1 }]}>Weight</Text>
        <Text style={[styles.cell, { flex: 1 }]}>Score</Text>
        <Text style={[styles.cell, { flex: 4 }]}>Notes</Text>
      </View>
      {risk.sub_scores.map((s) => (
        <View key={s.name} style={styles.tableRow}>
          <Text style={[styles.cell, { flex: 3 }]}>{t(`sub.name.${s.name}`)}</Text>
          <Text style={[styles.cell, { flex: 1 }]}>{Math.round(s.weight * 100)}%</Text>
          <Text style={[styles.cell, { flex: 1, fontWeight: 700 }]}>{s.score}/100</Text>
          <Text style={[styles.cell, { flex: 4, fontSize: 8 }]}>
            {s.notes.join("; ")}
          </Text>
        </View>
      ))}
      <Text style={[styles.small, { marginTop: 8 }]}>
        Weighted sub-score: {risk.weighted_score}/100 · Final (after caps): {risk.score}/100
      </Text>

      {/* Hard caps */}
      {risk.applied_caps.length > 0 && (
        <>
          <Text style={styles.h2}>{t("caps.title")}</Text>
          {risk.applied_caps.map((c) => (
            <View key={c.code} style={styles.capBox}>
              <Text style={{ fontSize: 9, fontWeight: 700 }}>
                {c.code} · {t("caps.maxScore", { value: c.cap_value })}
              </Text>
              <Text style={{ fontSize: 9, marginTop: 3 }}>{c.description}</Text>
            </View>
          ))}
        </>
      )}
      <PageFooter lang={lang} />
    </Page>
  );
}

function RecommendationsPage({ result, lang, t }: { result: ScanResponse; lang: Lang; t: (k: string, v?: Record<string, string | number>) => string }) {
  const recs = result.risk.recommendations;
  if (recs.length === 0) return null;
  return (
    <Page size="A4" style={styles.page}>
      <Text style={styles.h2}>{t("recs.title")}</Text>
      {recs.map((r, i) => (
        <View key={i} style={styles.recBox} wrap={false}>
          <View style={styles.row}>
            <Badge color={severityColor(r.priority)}>
              {t(`recs.priority.${r.priority}`)}
            </Badge>
            <Text style={{ fontSize: 10, fontWeight: 700, marginLeft: 6, flex: 1 }}>
              {r.title}
            </Text>
          </View>
          <Text style={{ fontSize: 9, marginTop: 4, color: "#374151" }}>
            {r.detail}
          </Text>
          {r.related.length > 0 && (
            <Text style={[styles.small, { marginTop: 3 }]}>
              Related: {r.related.slice(0, 6).join(", ")}
              {r.related.length > 6 ? ` (+${r.related.length - 6})` : ""}
            </Text>
          )}
        </View>
      ))}
      <PageFooter lang={lang} />
    </Page>
  );
}

function FindingsPage({ result, lang, t }: { result: ScanResponse; lang: Lang; t: (k: string, v?: Record<string, string | number>) => string }) {
  const flow = result.network.data_flow;
  const cookies = result.cookies;
  const policy = result.privacy_analysis;
  const forms = result.forms;
  return (
    <Page size="A4" style={styles.page}>
      {/* Data flow top 15 */}
      <Text style={styles.h2}>{t("flow.title")}</Text>
      <Text style={styles.small}>{t("flow.desc", { count: flow.length })}</Text>
      {flow.length > 0 && (
        <>
          <View style={[styles.tableHeader, { marginTop: 6 }]}>
            <Text style={[styles.cell, { flex: 4 }]}>{t("flow.h.domain")}</Text>
            <Text style={[styles.cell, { flex: 1 }]}>{t("flow.h.country")}</Text>
            <Text style={[styles.cell, { flex: 1 }]}>{t("flow.h.risk")}</Text>
            <Text style={[styles.cell, { flex: 3 }]}>{t("flow.h.categories")}</Text>
            <Text style={[styles.cell, { flex: 1, textAlign: "right" }]}>{t("flow.h.requests")}</Text>
          </View>
          {flow.slice(0, 15).map((d, i) => (
            <View key={i} style={styles.tableRow}>
              <Text style={[styles.cell, { flex: 4, fontSize: 9 }]}>{d.domain}</Text>
              <Text style={[styles.cell, { flex: 1, fontSize: 9 }]}>{d.country}</Text>
              <Text style={[styles.cell, { flex: 1, fontSize: 9, color: severityColor(d.risk) }]}>
                {d.risk}
              </Text>
              <Text style={[styles.cell, { flex: 3, fontSize: 8 }]}>
                {d.categories.join(", ") || "—"}
              </Text>
              <Text style={[styles.cell, { flex: 1, fontSize: 9, textAlign: "right" }]}>
                {d.request_count}
              </Text>
            </View>
          ))}
        </>
      )}

      {/* Cookies summary */}
      <Text style={styles.h2}>{t("cookies.title")}</Text>
      <Text style={{ fontSize: 9 }}>
        {t("cookies.desc", {
          total: cookies.summary.total_cookies ?? 0,
          thirdParty: cookies.summary.third_party_cookies ?? 0,
          session: cookies.summary.session_cookies ?? 0,
          storage: cookies.summary.total_storage ?? 0,
        })}
      </Text>
      <View style={{ marginTop: 4, flexDirection: "row", flexWrap: "wrap", gap: 4 }}>
        {(["necessary", "functional", "analytics", "marketing", "unknown"] as const).map((c) => (
          <Text key={c} style={{ fontSize: 8, marginRight: 8 }}>
            {t(`category.${c}`)}: {cookies.summary[`cookies_${c}`] ?? 0}
          </Text>
        ))}
      </View>

      {/* Privacy policy summary */}
      <Text style={styles.h2}>{t("privacy.title")}</Text>
      <Text style={{ fontSize: 9 }}>
        {policy.policy_url || t("privacy.noPolicy")}
      </Text>
      {policy.summary && (
        <Text style={{ fontSize: 9, marginTop: 4, color: "#374151" }}>{policy.summary}</Text>
      )}
      <Text style={[styles.small, { marginTop: 4 }]}>
        AI: {policy.provider}{policy.model ? ` · ${policy.model}` : ""} · Score: {policy.compliance_score}/100
      </Text>
      {policy.issues.length > 0 && (
        <View style={{ marginTop: 6 }}>
          <Text style={styles.h3}>{t("privacy.issues", { count: policy.issues.length })}</Text>
          {policy.issues.slice(0, 6).map((iss, i) => (
            <View key={i} style={{ marginBottom: 4 }}>
              <View style={styles.row}>
                <Badge color={severityColor(iss.severity)}>{iss.severity}</Badge>
                <Text style={{ fontSize: 9, fontWeight: 700, marginLeft: 6 }}>
                  {iss.category.replace(/_/g, " ")}
                </Text>
              </View>
              <Text style={{ fontSize: 9, marginTop: 2 }}>{iss.description}</Text>
            </View>
          ))}
        </View>
      )}

      {/* Forms summary */}
      <Text style={styles.h2}>{t("forms.title")}</Text>
      <Text style={{ fontSize: 9 }}>
        {t("forms.desc", {
          total: forms.summary.total_forms ?? 0,
          pii: forms.summary.forms_collecting_pii ?? 0,
          consent: forms.summary.forms_with_consent_checkbox ?? 0,
          link: forms.summary.forms_with_privacy_link ?? 0,
        })}
      </Text>

      <PageFooter lang={lang} />
    </Page>
  );
}

function DisclaimerPage({ lang, t }: { lang: Lang; t: (k: string, v?: Record<string, string | number>) => string }) {
  const disclaimer = lang === "de"
    ? "Dieser Bericht wurde automatisch aus passiven Beobachtungen der öffentlich zugänglichen Webseite generiert (HTTP-Responses, TLS-Handshake, clientseitiges DOM-Rendering). Es wurden keine aktiven Sicherheitstests (Payload-Fuzzing, Directory-Bruteforce, Exploit-Versuche) durchgeführt — § 202c StGB wird gewahrt. KI-generierte Textbausteine und Zusammenfassungen sind Entwürfe und stellen keine Rechtsberatung dar; sie müssen vor Verwendung durch qualifizierte Rechtsberater geprüft und angepasst werden. MSA DataX übernimmt keine Haftung für die rechtliche Eignung der hier enthaltenen Inhalte."
    : "This report was generated automatically from passive observations of the publicly accessible website (HTTP responses, TLS handshake, client-side DOM rendering). No active security testing (payload fuzzing, directory bruteforce, exploit attempts) was performed — § 202c StGB compliance maintained. AI-generated text drafts and summaries are drafts, not legal advice; they must be reviewed and adapted by qualified legal counsel before use. MSA DataX assumes no liability for the legal sufficiency of the content in this report.";
  return (
    <Page size="A4" style={styles.page}>
      <Text style={styles.h2}>{lang === "de" ? "Rechtlicher Hinweis" : "Legal notice"}</Text>
      <Text style={{ fontSize: 9, lineHeight: 1.6 }}>{disclaimer}</Text>
      <PageFooter lang={lang} />
    </Page>
  );
}

// ---------------------------------------------------------------------------
// Public API — single function that generates + downloads the PDF
// ---------------------------------------------------------------------------

export async function generateAndDownloadPdf(result: ScanResponse, lang: Lang): Promise<void> {
  const t = (k: string, v?: Record<string, string | number>) => translate(lang, k, v);

  const doc = (
    <Document
      title={`GDPR Scan — ${result.target}`}
      author="MSA DataX"
      subject={`GDPR Compliance Scan for ${result.target}`}
    >
      <CoverPage result={result} lang={lang} t={t} />
      <SummaryPage result={result} lang={lang} t={t} />
      {result.risk.recommendations.length > 0 && (
        <RecommendationsPage result={result} lang={lang} t={t} />
      )}
      <FindingsPage result={result} lang={lang} t={t} />
      <DisclaimerPage lang={lang} t={t} />
    </Document>
  );

  const blob = await pdf(doc).toBlob();
  const url = URL.createObjectURL(blob);
  const slug = result.target.replace(/^https?:\/\//, "").replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "").toLowerCase();
  const ts = (result.created_at ?? new Date().toISOString()).replace(/[:T]/g, "-").slice(0, 19);
  const a = document.createElement("a");
  a.href = url;
  a.download = `gdpr-scan-${slug}-${ts}.pdf`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
