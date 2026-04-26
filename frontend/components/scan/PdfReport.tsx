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
  // Phase-PDF-Big4: classification stripe + brand teal carry-over from
  // dashboard. Stripe uses the same teal as the dashboard so the
  // printed report visually matches the on-screen artefact.
  classification: "#0e7490",
  brand:          "#0891b2",
  panel:          "#f8fafc",
};

// ---------------------------------------------------------------------------
// Report metadata helpers (Phase-PDF-Big4)
// ---------------------------------------------------------------------------
//
// Big4-style audits identify every finding by a stable ID so that
// remediation tickets, follow-up reports, and supporting evidence can
// reference each issue across documents. We derive both the per-report
// ID and the per-finding IDs deterministically from the scan payload —
// re-rendering the same scan produces the same IDs, even from a
// re-imported JSON. No DB column needed.

/** Short, lowercase, alnum hash of any string. ~6 chars, collision-safe
 *  enough for "tells two scans of the same target apart". */
function shortHash(input: string): string {
  let h = 0;
  for (let i = 0; i < input.length; i++) h = ((h << 5) - h + input.charCodeAt(i)) | 0;
  // Force unsigned, base-36, pad to fixed width for uniform IDs.
  return (h >>> 0).toString(36).padStart(7, "0").slice(0, 7).toUpperCase();
}

/** Stable report ID like ``MSA-2026-04-25-A1B2C3D``. Date is the scan
 *  creation date (UTC, YYYY-MM-DD) so a re-run on the same day produces
 *  a different ID via the hash component. */
function reportId(result: ScanResponse): string {
  const dt = result.created_at ? new Date(result.created_at) : new Date();
  const yyyy = dt.getUTCFullYear();
  const mm = String(dt.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(dt.getUTCDate()).padStart(2, "0");
  const h = shortHash((result.id ?? "") + result.target + (result.created_at ?? ""));
  return `MSA-${yyyy}-${mm}-${dd}-${h}`;
}

/** Per-finding ID. ``prefix`` is a domain marker (DSGVO / SEC / PERF).
 *  Index is 1-based for human reading. Width-3 zero-padded so IDs sort
 *  lexicographically the same as numerically. */
function findingId(prefix: "DSGVO" | "SEC" | "PERF", index: number): string {
  return `F-${prefix}-${String(index).padStart(3, "0")}`;
}

const styles = StyleSheet.create({
  page: {
    padding: 40,
    fontSize: 10,
    fontFamily: "Helvetica",
    color: COLORS.ink,
    // Keep Page-level lineHeight modest — react-pdf applies it to every
    // child and large fonts overflow their line box when it's too loose.
    // Big-font elements (h1/h2/scores) set their own lineHeight below.
    lineHeight: 1.35,
  },
  // Chapter title. 18pt fits on one A4 line for typical German titles like
  // "Technische & organisatorische Maßnahmen (Art. 32 DSGVO)" with ~515pt
  // content width; at 22pt the line wrapped AND the line-height collapsed.
  h1: {
    fontSize: 18, fontWeight: 700,
    lineHeight: 1.25,
    marginBottom: 10,
  },
  h2: {
    fontSize: 14, fontWeight: 700,
    lineHeight: 1.3,
    marginTop: 16, marginBottom: 8,
    borderBottom: `1pt solid ${COLORS.border}`,
    paddingBottom: 4,
  },
  h3: {
    fontSize: 11, fontWeight: 700,
    lineHeight: 1.3,
    marginTop: 10, marginBottom: 4,
  },
  // Small kicker above a chapter title ("KAPITEL 4" / "CHAPTER 4")
  kicker: {
    fontSize: 8,
    fontWeight: 700,
    letterSpacing: 1.5,
    color: COLORS.muted,
    textTransform: "uppercase",
    marginBottom: 4,
  },
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
    paddingHorizontal: 40,
  },
  coverLogo: {
    fontSize: 30, fontWeight: 700,
    color: "#06b6d4",
    letterSpacing: 2,
    // Explicit lineHeight — at the default inherited 1.35, a fontSize-30
    // text's line box is 40.5pt tall but the glyph ascender reaches above
    // it; the next stacked Text overlaps. 1.2 gives exact breathing room.
    lineHeight: 1.2,
    marginBottom: 28,
    textAlign: "center",
  },
  coverTitle: {
    fontSize: 18,
    fontWeight: 700,
    lineHeight: 1.3,
    marginBottom: 6,
    textAlign: "center",
  },
  coverUrl: {
    fontSize: 10,
    color: COLORS.muted,
    textAlign: "center",
    marginBottom: 40,
    lineHeight: 1.3,
  },
  coverScore: {
    fontSize: 84,
    fontWeight: 700,
    lineHeight: 1,
    marginBottom: 4,
    textAlign: "center",
  },
  coverOf: {
    fontSize: 11,
    color: COLORS.muted,
    marginBottom: 14,
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
    flexDirection: "row",
    justifyContent: "space-between",
    fontSize: 7,
    color: COLORS.muted,
    borderTop: `0.5pt solid ${COLORS.border}`,
    paddingTop: 6,
  },
  // Big4 reports stripe a classification on every page. We render it as
  // a tiny ribbon at the top of each non-cover page.
  classificationRibbon: {
    position: "absolute",
    top: 0, left: 0, right: 0,
    backgroundColor: COLORS.classification,
    paddingVertical: 3,
    paddingHorizontal: 40,
    flexDirection: "row",
    justifyContent: "space-between",
    fontSize: 7,
    color: "#fff",
    letterSpacing: 1.5,
    textTransform: "uppercase",
    fontWeight: 700,
  },
  // Per-finding card for the Big4-style enumeration: ID + severity +
  // title up top, body in the middle, owner/due/status row at the
  // bottom for the customer's PM to fill in.
  findingCard: {
    border: `0.5pt solid ${COLORS.border}`,
    backgroundColor: "#fff",
    padding: 10,
    marginBottom: 8,
  },
  findingHeaderRow: {
    flexDirection: "row",
    alignItems: "center",
    marginBottom: 4,
  },
  findingId: {
    fontSize: 8,
    fontFamily: "Courier",
    color: COLORS.muted,
    marginRight: 8,
    letterSpacing: 0.5,
  },
  trackerRow: {
    flexDirection: "row",
    marginTop: 8,
    paddingTop: 6,
    borderTop: `0.5pt dashed ${COLORS.border}`,
    fontSize: 8,
    color: COLORS.muted,
  },
  trackerCell: {
    flexDirection: "row",
    marginRight: 18,
  },
  trackerLabel: {
    fontWeight: 700,
    marginRight: 4,
    color: COLORS.muted,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  trackerField: {
    minWidth: 60,
    borderBottom: `0.5pt solid ${COLORS.border}`,
    paddingBottom: 1,
  },
  // Methodology + References pages share a panel look — light bg,
  // bordered, two-column-friendly when needed.
  panel: {
    backgroundColor: COLORS.panel,
    border: `0.5pt solid ${COLORS.border}`,
    padding: 12,
    marginBottom: 10,
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

// Severity ordering — high → medium → low. Used to sort findings so
// the auditor reads worst first in the per-finding enumerations.
function severityRank(s: string): number {
  return s === "high" ? 0 : s === "medium" ? 1 : 2;
}

// Big4-style finding card: stable ID + severity badge + title up top,
// description + optional verbatim excerpt in the middle, blank
// Owner / Due / Status fields at the bottom for the customer's PM
// to fill in. ``wrap={false}`` keeps a card on one page rather than
// splitting mid-finding which destroys readability.
function FindingCard({
  fid, severity, title, description, excerpt, lang, t,
}: {
  fid: string;
  severity: string;
  title: string;
  description: string;
  excerpt?: string | null;
  lang: Lang;
  t: (k: string, v?: Record<string, string | number>) => string;
}) {
  return (
    <View style={styles.findingCard} wrap={false}>
      <View style={styles.findingHeaderRow}>
        <Text style={styles.findingId}>{fid}</Text>
        <Badge color={severityColor(severity)}>{t(`severity.${severity}`)}</Badge>
        <Text style={{ fontSize: 10, fontWeight: 700, marginLeft: 8, flex: 1 }}>
          {title}
        </Text>
      </View>
      <Text style={{ fontSize: 9, color: "#374151", marginTop: 2 }}>
        {description}
      </Text>
      {excerpt && (
        <Text style={{ fontSize: 8, fontStyle: "italic", color: COLORS.muted, marginTop: 4, paddingLeft: 8, borderLeft: `2pt solid ${COLORS.border}` }}>
          {`"${excerpt}"`}
        </Text>
      )}
      <View style={styles.trackerRow}>
        <View style={styles.trackerCell}>
          <Text style={styles.trackerLabel}>{t("pdf.finding.owner")}:</Text>
          <Text style={styles.trackerField}> </Text>
        </View>
        <View style={styles.trackerCell}>
          <Text style={styles.trackerLabel}>{t("pdf.finding.due")}:</Text>
          <Text style={styles.trackerField}> </Text>
        </View>
        <View style={styles.trackerCell}>
          <Text style={styles.trackerLabel}>{t("pdf.finding.status")}:</Text>
          <Text style={styles.trackerField}>{t("pdf.finding.statusOpen")}</Text>
        </View>
      </View>
      <Text style={{ fontSize: 7, color: COLORS.muted, marginTop: 6, fontFamily: "Courier" }}>
        {lang === "de" ? "Empfohlene Maßnahme:" : "Recommended action:"} {t("pdf.finding.refReco")}
      </Text>
    </View>
  );
}

function PageFooter({ lang, reportId: rid }: { lang: Lang; reportId: string }) {
  // Footer is split into three columns so a Big4-style page bears its
  // own provenance: brand on the left, report ID center, page count
  // right. ``fixed`` makes react-pdf stamp it on every page of the
  // hosting <Page>.
  return (
    <View style={styles.footer} fixed>
      <Text>MSA DataX · {translate(lang, "app.title")}</Text>
      <Text style={{ fontFamily: "Courier" }}>{rid}</Text>
      <Text
        render={({ pageNumber, totalPages }) =>
          translate(lang, "pdf.footer.page", { current: pageNumber, total: totalPages })
        }
      />
    </View>
  );
}

// Top-of-page classification ribbon — Big4 reports flag every page with
// the document's confidentiality level so a stray printout can't be
// mistaken for a public artefact. We keep it lightweight (one row,
// 3pt vertical) so it doesn't compete with content.
function ClassificationRibbon({ lang, reportId: rid }: { lang: Lang; reportId: string }) {
  return (
    <View style={styles.classificationRibbon} fixed>
      <Text>{translate(lang, "pdf.classification")}</Text>
      <Text style={{ fontFamily: "Courier" }}>{rid}</Text>
    </View>
  );
}

// Matches the dashboard ChapterHeader visually: top rule + kicker +
// large title + article-reference subtitle. Used at the top of each
// audience chapter so the PDF reader lands with context.
function ChapterDivider({
  lang, number, titleKey, refKey,
}: {
  lang: Lang;
  number: number;
  titleKey: string;
  refKey: string;
}) {
  return (
    <View style={{ marginBottom: 14 }}>
      <View style={{ borderTopWidth: 2, borderTopColor: "#cbd5e1", marginBottom: 12 }} />
      <Text style={styles.kicker}>
        {translate(lang, "chapter.kicker")} {number}
      </Text>
      <Text style={styles.h1}>{translate(lang, titleKey)}</Text>
      <Text style={{ fontSize: 9, color: COLORS.muted, lineHeight: 1.45, marginTop: 2 }}>
        {translate(lang, refKey)}
      </Text>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Report body
// ---------------------------------------------------------------------------

function CoverPage({ result, lang, t }: { result: ScanResponse; lang: Lang; t: (k: string, v?: Record<string, string | number>) => string }) {
  const rid = reportId(result);
  const issuedAt = result.created_at ? new Date(result.created_at) : new Date();
  // Engagement-block fields are deliberately concrete (not "auto-generated")
  // so the PDF reads as an audit deliverable, not a tool dump. Methodology
  // pointer is the page reference into the report so a reader who lands on
  // the cover knows where to read the limits of the scan.
  return (
    <Page size="A4" style={styles.page}>
      {/* Solid classification stripe — wider on the cover than on body
          pages because the cover is the first thing a reader sees. */}
      <View
        style={{
          backgroundColor: COLORS.classification,
          paddingVertical: 6, paddingHorizontal: 40,
          flexDirection: "row", justifyContent: "space-between",
          fontSize: 8, color: "#fff",
          letterSpacing: 1.5, textTransform: "uppercase", fontWeight: 700,
        }}
      >
        <Text>{t("pdf.classification")}</Text>
        <Text>{t("pdf.cover.draft")}</Text>
      </View>

      <View style={styles.cover}>
        {/* Brand + product name. Each Text is its own block with explicit
            margin, which is what react-pdf wants for reliable vertical
            stacking at large font sizes. */}
        <Text style={styles.coverLogo}>MSA | DataX</Text>
        <Text style={styles.coverTitle}>{t("app.title")}</Text>
        <Text style={styles.coverUrl}>{result.target}</Text>

        {/* Score block */}
        <Text style={[styles.coverScore, { color: ratingColor(result.risk.rating) }]}>
          {result.risk.score}
        </Text>
        <Text style={styles.coverOf}>{t("risk.of100")}</Text>
        <View style={{ marginBottom: 28 }}>
          <Badge color={ratingColor(result.risk.rating)}>
            {t(`risk.rating.${result.risk.rating}`)}
          </Badge>
        </View>

        {/* Engagement-summary panel: report ID, issue date, version,
            engagement scope, methodology pointer. Fixed-width left
            column for labels so the values line up consistently. */}
        <View
          style={{
            width: "85%",
            border: `0.5pt solid ${COLORS.border}`,
            backgroundColor: COLORS.panel,
            padding: 14,
          }}
        >
          <CoverMetaRow label={t("pdf.cover.reportId")} value={rid} mono />
          <CoverMetaRow label={t("pdf.cover.issued")} value={issuedAt.toLocaleString(lang)} />
          <CoverMetaRow label={t("pdf.cover.version")} value="v1.0" />
          <CoverMetaRow label={t("pdf.cover.scope")} value={t("pdf.cover.scopeValue")} />
          <CoverMetaRow label={t("pdf.cover.methodology")} value={t("pdf.cover.methodologyValue")} />
          <CoverMetaRow label={t("pdf.cover.preparedBy")} value="MSA DataX GDPR Scanner" />
        </View>
      </View>
      {/* No PageFooter on the cover — Big4 cover pages are deliberately
          chrome-free. The report ID is already in the engagement panel. */}
    </Page>
  );
}

function CoverMetaRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <View style={{ flexDirection: "row", marginBottom: 4 }}>
      <Text
        style={{
          width: 110, fontSize: 8, fontWeight: 700,
          textTransform: "uppercase", letterSpacing: 0.8,
          color: COLORS.muted, paddingTop: 1,
        }}
      >
        {label}
      </Text>
      <Text
        style={{
          flex: 1, fontSize: 9,
          fontFamily: mono ? "Courier" : "Helvetica",
        }}
      >
        {value}
      </Text>
    </View>
  );
}

function SummaryPage({ result, lang, t }: { result: ScanResponse; lang: Lang; t: (k: string, v?: Record<string, string | number>) => string }) {
  const risk = result.risk;
  const rid = reportId(result);
  return (
    <Page size="A4" style={[styles.page, { paddingTop: 50 }]}>
      <ClassificationRibbon lang={lang} reportId={rid} />
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
      <PageFooter lang={lang} reportId={rid} />
    </Page>
  );
}

function RecommendationsPage({ result, lang, t }: { result: ScanResponse; lang: Lang; t: (k: string, v?: Record<string, string | number>) => string }) {
  const recs = result.risk.recommendations;
  if (recs.length === 0) return null;
  const rid = reportId(result);
  return (
    <Page size="A4" style={[styles.page, { paddingTop: 50 }]}>
      <ClassificationRibbon lang={lang} reportId={rid} />
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
      <PageFooter lang={lang} reportId={rid} />
    </Page>
  );
}

function PrivacyChapterPage({
  result, lang, t,
}: {
  result: ScanResponse;
  lang: Lang;
  t: (k: string, v?: Record<string, string | number>) => string;
}) {
  const flow = result.network.data_flow;
  const cookies = result.cookies;
  const policy = result.privacy_analysis;
  const forms = result.forms;
  const consent = result.consent;
  const channels = result.contact_channels;
  const widgets = result.widgets;
  const rid = reportId(result);

  return (
    <Page size="A4" style={[styles.page, { paddingTop: 50 }]}>
      <ClassificationRibbon lang={lang} reportId={rid} />
      <ChapterDivider
        lang={lang} number={1}
        titleKey="chapter.privacy.title"
        refKey="chapter.privacy.ref"
      />

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
        <View style={{ marginTop: 8 }}>
          <Text style={styles.h3}>{t("privacy.issues", { count: policy.issues.length })}</Text>
          {/* Per-finding cards. Sorted high → medium → low so the
              auditor reads worst first. Each card carries a stable ID
              + Owner / Due / Status row to make the PDF actionable
              as a tracking document, not just a snapshot. */}
          {[...policy.issues]
            .sort((a, b) => severityRank(a.severity) - severityRank(b.severity))
            .slice(0, 8)
            .map((iss, i) => (
              <FindingCard
                key={i}
                fid={findingId("DSGVO", i + 1)}
                severity={iss.severity}
                title={iss.category.replace(/_/g, " ")}
                description={iss.description}
                excerpt={iss.excerpt}
                lang={lang}
                t={t}
              />
            ))}
        </View>
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
      <View style={{ marginTop: 4, flexDirection: "row", flexWrap: "wrap" }}>
        {(["necessary", "functional", "analytics", "marketing", "unknown"] as const).map((c) => (
          <Text key={c} style={{ fontSize: 8, marginRight: 10 }}>
            {t(`category.${c}`)}: {cookies.summary[`cookies_${c}`] ?? 0}
          </Text>
        ))}
      </View>

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

      {/* Consent simulation (only when the user opted in) */}
      {consent && (
        <>
          <Text style={styles.h2}>{t("consent.title")}</Text>
          <Text style={{ fontSize: 9 }}>{consent.note}</Text>
          {consent.ux_audit && consent.ux_audit.findings.length > 0 && (
            <View style={{ marginTop: 4 }}>
              <Text style={styles.h3}>
                {t("consent.ux.dark.title", { count: consent.ux_audit.findings.length })}
              </Text>
              {consent.ux_audit.findings.map((f, i) => (
                <View key={i} style={{ marginBottom: 2, flexDirection: "row", alignItems: "flex-start" }}>
                  <Badge color={severityColor(f.severity)}>{f.severity}</Badge>
                  <Text style={{ fontSize: 8, marginLeft: 6, flex: 1 }}>
                    {f.code.replace(/_/g, " ")} — {f.description}
                  </Text>
                </View>
              ))}
            </View>
          )}
          {consent.diff && (
            <Text style={[styles.small, { marginTop: 4 }]}>
              Post-consent diff: {consent.diff.new_cookies.length} new cookie(s),{" "}
              {consent.diff.new_storage.length} new storage entry/entries,{" "}
              {consent.diff.new_data_flow.length} new domain(s).
            </Text>
          )}
        </>
      )}

      {/* Contact channels — one line per kind with country */}
      {channels.channels.length > 0 && (
        <>
          <Text style={styles.h2}>{t("channels.title")}</Text>
          <Text style={styles.small}>
            {t("channels.desc", {
              count: channels.channels.length,
              us: channels.summary.us_transfer_channels ?? 0,
              unknown: channels.summary.unknown_jurisdiction_channels ?? 0,
            })}
          </Text>
          <View style={{ marginTop: 4 }}>
            {Object.entries(
              channels.channels.reduce<Record<string, { count: number; country: string }>>(
                (acc, c) => {
                  const e = acc[c.kind] ?? { count: 0, country: c.country };
                  e.count += 1;
                  e.country = c.country;
                  acc[c.kind] = e;
                  return acc;
                }, {},
              ),
            ).sort(([, a], [, b]) => b.count - a.count).map(([kind, info], i) => (
              <View key={i} style={{ flexDirection: "row", marginBottom: 1 }}>
                <Text style={{ fontSize: 9, width: 160 }}>{kind.replace(/_/g, " ")}</Text>
                <Text style={{ fontSize: 9, width: 40 }}>×{info.count}</Text>
                <Text style={{ fontSize: 9, color: COLORS.muted }}>{info.country}</Text>
              </View>
            ))}
          </View>
        </>
      )}

      {/* Third-party widgets */}
      {widgets.widgets.length > 0 && (
        <>
          <Text style={styles.h2}>{t("widgets.title")}</Text>
          <Text style={styles.small}>
            {t("widgets.desc", {
              total: widgets.widgets.length,
              video: widgets.summary.non_enhanced_video ?? 0,
              chat:  widgets.summary.category_chat ?? 0,
              auth:  widgets.summary.category_auth ?? 0,
              enhanced: widgets.summary.privacy_enhanced ?? 0,
            })}
          </Text>
        </>
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

      <PageFooter lang={lang} reportId={rid} />
    </Page>
  );
}

function SecurityAuditPage({
  result, lang, t,
}: {
  result: ScanResponse;
  lang: Lang;
  t: (k: string, v?: Record<string, string | number>) => string;
}) {
  const sec = result.security;
  if (!sec || sec.error) return null;
  const rid = reportId(result);

  const tls = sec.tls;
  const certDaysLabel = (() => {
    if (!tls || tls.cert_expires_days == null) return t("security.tls.unknown");
    if (tls.cert_expires_days < 0) return t("security.tls.ago", { days: Math.abs(tls.cert_expires_days) });
    return t("security.tls.in", { days: tls.cert_expires_days });
  })();
  const hstsLabel = (() => {
    if (!tls || tls.hsts_max_age_days == null) return t("security.tls.missing");
    return `${tls.hsts_max_age_days}d${tls.hsts_preload_eligible ? t("security.tls.preloadReady") : ""}`;
  })();

  const libs = result.vulnerable_libraries;

  return (
    <Page size="A4" style={[styles.page, { paddingTop: 50 }]}>
      <ClassificationRibbon lang={lang} reportId={rid} />
      {/* Kapitel 2 divider — mirrors dashboard ChapterHeader */}
      <ChapterDivider
        lang={lang} number={2}
        titleKey="chapter.security.title"
        refKey="chapter.security.ref"
      />

      {/* TLS / HTTPS strip. No `gap` (unreliable in react-pdf) — use
          marginRight on all-but-last child to space the stat boxes. */}
      <Text style={styles.h2}>{t("security.title")}</Text>
      <View style={[styles.row, { marginTop: 4 }]}>
        <TlsPdfStat label={t("security.tls.httpsEnforced")}
                    value={tls?.https_enforced ? t("security.tls.yes") : t("security.tls.noHttp")}
                    ok={!!tls?.https_enforced}
                    last={false} />
        <TlsPdfStat label={t("security.tls.version")}
                    value={tls?.tls_version ?? t("security.tls.unknown")}
                    ok={tls?.tls_version === "TLSv1.3" || tls?.tls_version === "TLSv1.2"}
                    last={false} />
        <TlsPdfStat label={t("security.tls.certExpires")}
                    value={certDaysLabel}
                    critical={tls?.cert_expires_days != null && tls.cert_expires_days < 0}
                    warning={tls?.cert_expires_days != null && tls.cert_expires_days >= 0 && tls.cert_expires_days < 14}
                    ok={tls?.cert_expires_days != null && tls.cert_expires_days >= 14}
                    last={false} />
        <TlsPdfStat label={t("security.tls.hsts")}
                    value={hstsLabel}
                    ok={(tls?.hsts_max_age_days ?? 0) >= 180}
                    last />
      </View>

      {/* Mixed content alert */}
      {sec.mixed_content_count > 0 && (
        <View style={[styles.capBox, { marginTop: 10 }]}>
          <Text style={{ fontSize: 9, fontWeight: 700 }}>
            {t("security.mixedTitle", { count: sec.mixed_content_count })}
          </Text>
          <Text style={{ fontSize: 9, marginTop: 3 }}>{t("security.mixedDesc")}</Text>
          {sec.mixed_content_samples.length > 0 && (
            <View style={{ marginTop: 3 }}>
              {sec.mixed_content_samples.slice(0, 3).map((u, i) => (
                <Text key={i} style={{ fontSize: 8, fontFamily: "Courier" }}>• {u}</Text>
              ))}
            </View>
          )}
        </View>
      )}

      {/* Security headers table */}
      <Text style={[styles.h3, { marginTop: 10 }]}>
        {lang === "de" ? "HTTP-Sicherheits-Header" : "HTTP security headers"}
      </Text>
      <View style={[styles.tableHeader, { marginTop: 4 }]}>
        <Text style={[styles.cell, { flex: 4 }]}>{t("security.h.header")}</Text>
        <Text style={[styles.cell, { flex: 1 }]}>{t("security.h.status")}</Text>
        <Text style={[styles.cell, { flex: 1 }]}>{t("security.h.severity")}</Text>
        <Text style={[styles.cell, { flex: 5 }]}>{t("security.h.note")}</Text>
      </View>
      {sec.headers.map((h, i) => (
        <View key={i} style={styles.tableRow}>
          <Text style={[styles.cell, { flex: 4, fontSize: 8, fontFamily: "Courier" }]}>
            {h.name}
          </Text>
          <Text style={[styles.cell, { flex: 1, fontSize: 8,
                                        color: h.present ? COLORS.low : COLORS.high }]}>
            {h.present ? t("security.header.present") : t("security.header.missing")}
          </Text>
          <Text style={[styles.cell, { flex: 1, fontSize: 8, color: severityColor(h.severity) }]}>
            {h.severity}
          </Text>
          <Text style={[styles.cell, { flex: 5, fontSize: 8 }]}>{h.note}</Text>
        </View>
      ))}

      {/* Information leak */}
      {sec.info_leak_headers.length > 0 && (
        <>
          <Text style={[styles.h3, { marginTop: 10 }]}>{t("security.infoLeak.title")}</Text>
          {sec.info_leak_headers.map((h, i) => (
            <View key={i} style={{ marginBottom: 2 }}>
              <Text style={{ fontSize: 8, fontFamily: "Courier" }}>
                {h.name}: {h.value}
              </Text>
              <Text style={{ fontSize: 8, color: COLORS.muted }}>— {h.leaks}</Text>
            </View>
          ))}
        </>
      )}

      {/* DNS hardening summary */}
      {sec.dns && (
        <>
          <Text style={styles.h3}>
            {t("security.dns.title")}{sec.dns.domain ? ` — ${sec.dns.domain}` : ""}
          </Text>
          <View style={[styles.row, { marginTop: 2 }]}>
            <DnsPdfStat label={t("security.dns.spf")}   ok={sec.dns.spf_present} last={false} />
            <DnsPdfStat label={t("security.dns.dmarc")} ok={sec.dns.dmarc_present && sec.dns.dmarc_policy !== "none"}
                        extra={sec.dns.dmarc_present ? `p=${sec.dns.dmarc_policy}` : undefined} last={false} />
            <DnsPdfStat label={t("security.dns.dnssec")} ok={sec.dns.dnssec_enabled} last={false} />
            <DnsPdfStat label={t("security.dns.caa")}    ok={sec.dns.caa_present} last />
          </View>
        </>
      )}

      {/* SRI gaps */}
      {sec.sri_missing && sec.sri_missing.length > 0 && (
        <>
          <Text style={styles.h3}>{t("security.sri.title")}</Text>
          <Text style={{ fontSize: 9 }}>
            {t("security.sri.missing", { count: sec.sri_missing.length })}
          </Text>
          {sec.sri_missing.slice(0, 5).map((u, i) => (
            <Text key={i} style={{ fontSize: 8, fontFamily: "Courier", marginLeft: 10 }}>
              • {u}
            </Text>
          ))}
        </>
      )}

      {/* security.txt */}
      <Text style={[styles.small, { marginTop: 8 }]}>
        {t("security.securityTxt.title")}: {sec.security_txt_url
          ? t("security.securityTxt.present")
          : t("security.securityTxt.missing")}
      </Text>

      {/* Vulnerable JS libraries */}
      {libs && libs.libraries.length > 0 && (
        <>
          <Text style={styles.h2}>{t("vulnLibs.title")}</Text>
          <Text style={styles.small}>
            {t("vulnLibs.desc", {
              total:  libs.summary.total  ?? libs.libraries.length,
              high:   libs.summary.high   ?? 0,
              medium: libs.summary.medium ?? 0,
              low:    libs.summary.low    ?? 0,
            })}
          </Text>
          <View style={[styles.tableHeader, { marginTop: 6 }]}>
            <Text style={[styles.cell, { flex: 2 }]}>{t("vulnLibs.h.lib")}</Text>
            <Text style={[styles.cell, { flex: 1 }]}>{t("vulnLibs.h.version")}</Text>
            <Text style={[styles.cell, { flex: 1 }]}>{t("vulnLibs.h.severity")}</Text>
            <Text style={[styles.cell, { flex: 1 }]}>{t("vulnLibs.h.fixed")}</Text>
            <Text style={[styles.cell, { flex: 2 }]}>{t("vulnLibs.h.cves")}</Text>
            <Text style={[styles.cell, { flex: 4 }]}>{t("vulnLibs.h.advisory")}</Text>
          </View>
          {libs.libraries.slice(0, 20).map((v, i) => (
            <View key={i} style={styles.tableRow}>
              <Text style={[styles.cell, { flex: 2, fontSize: 9 }]}>{v.library}</Text>
              <Text style={[styles.cell, { flex: 1, fontSize: 9, fontFamily: "Courier" }]}>
                {v.detected_version}
              </Text>
              <Text style={[styles.cell, { flex: 1, fontSize: 9, color: severityColor(v.severity) }]}>
                {v.severity}
              </Text>
              <Text style={[styles.cell, { flex: 1, fontSize: 8 }]}>{v.fixed_in ?? "—"}</Text>
              <Text style={[styles.cell, { flex: 2, fontSize: 8, fontFamily: "Courier" }]}>
                {v.cves.join(", ") || "—"}
              </Text>
              <Text style={[styles.cell, { flex: 4, fontSize: 8 }]}>{v.advisory ?? ""}</Text>
            </View>
          ))}
        </>
      )}

      {/* Compliance footer note */}
      <Text style={[styles.small, { marginTop: 14, fontStyle: "italic" }]}>
        {t("security.footer")}
      </Text>

      <PageFooter lang={lang} reportId={rid} />
    </Page>
  );
}

// Compact DNS status box — four of these fit side-by-side on the
// security page. Same colour semantics as the TLS strip (green = ok,
// red = missing). `last` controls the right margin so the row aligns.
function DnsPdfStat({
  label, ok, extra, last,
}: {
  label: string; ok: boolean; extra?: string; last?: boolean;
}) {
  const color = ok ? COLORS.low : COLORS.high;
  return (
    <View style={{
      flex: 1,
      borderWidth: 1, borderColor: color, borderRadius: 3,
      padding: 4,
      marginRight: last ? 0 : 4,
    }}>
      <Text style={{ fontSize: 7, color: COLORS.muted, textTransform: "uppercase", letterSpacing: 0.5 }}>
        {label}
      </Text>
      <Text style={{ fontSize: 9, fontWeight: 700, color, marginTop: 1 }}>
        {ok ? "OK" : "—"}
        {extra && <Text style={{ fontWeight: 400, color: COLORS.muted }}>{` (${extra})`}</Text>}
      </Text>
    </View>
  );
}

function TlsPdfStat({
  label, value, ok, warning, critical, last,
}: {
  label: string; value: string; ok?: boolean; warning?: boolean; critical?: boolean;
  last?: boolean;
}) {
  const color = critical ? COLORS.critical
              : warning ? COLORS.medium
              : ok ? COLORS.low
              : COLORS.high;
  return (
    <View style={{
      flex: 1,
      borderWidth: 1, borderColor: color, borderRadius: 3,
      padding: 6,
      backgroundColor: "#fafafa",
      marginRight: last ? 0 : 6,
    }}>
      <Text style={{
        fontSize: 7, color: COLORS.muted,
        textTransform: "uppercase", letterSpacing: 0.5,
        marginBottom: 3,
      }}>
        {label}
      </Text>
      <Text style={{ fontSize: 10, fontWeight: 700, color, lineHeight: 1.2 }}>
        {value}
      </Text>
    </View>
  );
}

// Methodology page — every Big4 audit deliverable opens with one. Tells
// the reader what was inspected, which methods, and where the audit
// stops on purpose. We render it as the second page so the rest of the
// findings have implicit context. Source of truth: this page must list
// what the scanner ACTUALLY does — when a new module is added, mirror
// it here so the report stays honest about its own capabilities.
function MethodologyPage({
  lang, t, rid,
}: {
  lang: Lang;
  t: (k: string, v?: Record<string, string | number>) => string;
  rid: string;
}) {
  return (
    <Page size="A4" style={[styles.page, { paddingTop: 50 }]}>
      <ClassificationRibbon lang={lang} reportId={rid} />
      <Text style={styles.h1}>{t("pdf.methodology.title")}</Text>
      <Text style={[styles.muted, { marginBottom: 12 }]}>
        {t("pdf.methodology.intro")}
      </Text>

      <View style={styles.panel}>
        <Text style={styles.h3}>{t("pdf.methodology.scopeTitle")}</Text>
        {[
          "pdf.methodology.scope.crawl",
          "pdf.methodology.scope.network",
          "pdf.methodology.scope.cookies",
          "pdf.methodology.scope.policy",
          "pdf.methodology.scope.forms",
          "pdf.methodology.scope.consent",
          "pdf.methodology.scope.security",
          "pdf.methodology.scope.dns",
          "pdf.methodology.scope.libs",
        ].map((k) => (
          <Text key={k} style={{ fontSize: 9, marginBottom: 3 }}>
            • {t(k)}
          </Text>
        ))}
      </View>

      <View style={styles.panel}>
        <Text style={styles.h3}>{t("pdf.methodology.outOfScopeTitle")}</Text>
        {[
          "pdf.methodology.outOfScope.activeProbing",
          "pdf.methodology.outOfScope.dnsRebinding",
          "pdf.methodology.outOfScope.geoIp",
          "pdf.methodology.outOfScope.authedCrawl",
          "pdf.methodology.outOfScope.legalAdvice",
        ].map((k) => (
          <Text key={k} style={{ fontSize: 9, marginBottom: 3 }}>
            • {t(k)}
          </Text>
        ))}
      </View>

      <View style={styles.panel}>
        <Text style={styles.h3}>{t("pdf.methodology.limitationsTitle")}</Text>
        {[
          "pdf.methodology.limitations.snapshot",
          "pdf.methodology.limitations.languages",
          "pdf.methodology.limitations.aiProvider",
          "pdf.methodology.limitations.headlessRendering",
        ].map((k) => (
          <Text key={k} style={{ fontSize: 9, marginBottom: 3 }}>
            • {t(k)}
          </Text>
        ))}
      </View>

      <PageFooter lang={lang} reportId={rid} />
    </Page>
  );
}

// References / glossary appendix — cited rulings + articles all in one
// place so the reader doesn't have to chase individual finding cards
// for the legal anchor. Stable list (per CLAUDE.md conventions); when a
// new ruling is cited in scoring.py, add it here too.
function ReferencesPage({
  lang, t, rid,
}: {
  lang: Lang;
  t: (k: string, v?: Record<string, string | number>) => string;
  rid: string;
}) {
  // Each entry: short identifier (left col) + plain-language summary
  // (right col). Identifiers are PDF-friendly (no italics, no markdown).
  const refs: { id: string; bodyKey: string }[] = [
    { id: "Art. 6 DSGVO",                 bodyKey: "pdf.references.art6" },
    { id: "Art. 7(2) DSGVO",              bodyKey: "pdf.references.art7" },
    { id: "Art. 13 DSGVO",                bodyKey: "pdf.references.art13" },
    { id: "Art. 32 DSGVO",                bodyKey: "pdf.references.art32" },
    { id: "Art. 44 ff. DSGVO",            bodyKey: "pdf.references.art44" },
    { id: "§ 25 TDDDG",                   bodyKey: "pdf.references.tdddg" },
    { id: "§ 5 TMG",                      bodyKey: "pdf.references.tmg" },
    { id: "EuGH Planet49 (C-673/17)",     bodyKey: "pdf.references.planet49" },
    { id: "EuGH Schrems II (C-311/18)",   bodyKey: "pdf.references.schremsII" },
    { id: "LG München I (3 O 17493/20)",  bodyKey: "pdf.references.lgMuenchen" },
    { id: "EDPB Guidelines 03/2022",      bodyKey: "pdf.references.edpb032022" },
    { id: "EDPB Opinion 8/2024",          bodyKey: "pdf.references.edpb082024" },
  ];
  return (
    <Page size="A4" style={[styles.page, { paddingTop: 50 }]}>
      <ClassificationRibbon lang={lang} reportId={rid} />
      <Text style={styles.h1}>{t("pdf.references.title")}</Text>
      <Text style={[styles.muted, { marginBottom: 12 }]}>
        {t("pdf.references.intro")}
      </Text>
      <View style={styles.tableHeader}>
        <Text style={[styles.cell, { flex: 3 }]}>{t("pdf.references.col.ref")}</Text>
        <Text style={[styles.cell, { flex: 7 }]}>{t("pdf.references.col.body")}</Text>
      </View>
      {refs.map((r) => (
        <View key={r.id} style={styles.tableRow} wrap={false}>
          <Text style={[styles.cell, { flex: 3, fontSize: 9, fontWeight: 700 }]}>
            {r.id}
          </Text>
          <Text style={[styles.cell, { flex: 7, fontSize: 9 }]}>
            {t(r.bodyKey)}
          </Text>
        </View>
      ))}
      <PageFooter lang={lang} reportId={rid} />
    </Page>
  );
}

function DisclaimerPage({ lang, t, rid }: { lang: Lang; t: (k: string, v?: Record<string, string | number>) => string; rid: string }) {
  const disclaimer = lang === "de"
    ? "Dieser Bericht wurde automatisch aus passiven Beobachtungen der öffentlich zugänglichen Webseite generiert (HTTP-Responses, TLS-Handshake, clientseitiges DOM-Rendering). Es wurden keine aktiven Sicherheitstests (Payload-Fuzzing, Directory-Bruteforce, Exploit-Versuche) durchgeführt — § 202c StGB wird gewahrt. KI-generierte Textbausteine und Zusammenfassungen sind Entwürfe und stellen keine Rechtsberatung dar; sie müssen vor Verwendung durch qualifizierte Rechtsberater geprüft und angepasst werden. MSA DataX übernimmt keine Haftung für die rechtliche Eignung der hier enthaltenen Inhalte."
    : "This report was generated automatically from passive observations of the publicly accessible website (HTTP responses, TLS handshake, client-side DOM rendering). No active security testing (payload fuzzing, directory bruteforce, exploit attempts) was performed — § 202c StGB compliance maintained. AI-generated text drafts and summaries are drafts, not legal advice; they must be reviewed and adapted by qualified legal counsel before use. MSA DataX assumes no liability for the legal sufficiency of the content in this report.";
  return (
    <Page size="A4" style={[styles.page, { paddingTop: 50 }]}>
      <ClassificationRibbon lang={lang} reportId={rid} />
      <Text style={styles.h2}>{lang === "de" ? "Rechtlicher Hinweis" : "Legal notice"}</Text>
      <Text style={{ fontSize: 9, lineHeight: 1.6 }}>{disclaimer}</Text>
      <PageFooter lang={lang} reportId={rid} />
    </Page>
  );
}

// ---------------------------------------------------------------------------
// Public API — single function that generates + downloads the PDF
// ---------------------------------------------------------------------------

export async function generateAndDownloadPdf(result: ScanResponse, lang: Lang): Promise<void> {
  const t = (k: string, v?: Record<string, string | number>) => translate(lang, k, v);
  const rid = reportId(result);

  const doc = (
    <Document
      title={`GDPR Scan — ${result.target}`}
      author="MSA DataX"
      subject={`GDPR Compliance Scan for ${result.target}`}
    >
      <CoverPage result={result} lang={lang} t={t} />
      {/* Methodology comes second — Big4-deliverable convention. The
          reader knows what was inspected before reading findings. */}
      <MethodologyPage lang={lang} t={t} rid={rid} />
      <SummaryPage result={result} lang={lang} t={t} />
      {result.risk.recommendations.length > 0 && (
        <RecommendationsPage result={result} lang={lang} t={t} />
      )}
      {/* Kapitel 1 — GDPR / Privacy (always shown) */}
      <PrivacyChapterPage result={result} lang={lang} t={t} />
      {/* Kapitel 2 — Security / Art. 32 (shown when security probe succeeded) */}
      {result.security && !result.security.error && (
        <SecurityAuditPage result={result} lang={lang} t={t} />
      )}
      {/* Cited articles + rulings appendix — last content page before
          the legal disclaimer. */}
      <ReferencesPage lang={lang} t={t} rid={rid} />
      <DisclaimerPage lang={lang} t={t} rid={rid} />
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
