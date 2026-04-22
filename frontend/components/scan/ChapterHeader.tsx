"use client";

// Visual chapter divider between the two audit halves (Privacy vs Security).
// Matches the PDF's chapter structure: kicker + title + article-ref subtitle.
//
// Why this pattern:
// - A plain <h2> got lost in the long card stack; an auditor scrolling
//   past doesn't notice they've moved from "Privacy" into "Security".
// - A tabbed nav would hide half the findings — a consent dark pattern
//   is both a Privacy and a Security concern, so silos produce blind
//   spots. Visual grouping without hiding keeps both audiences informed
//   while still giving each their obvious home section.

import { useLang } from "@/lib/LanguageContext";

export function ChapterHeader({
  id,
  number,
  titleKey,
  refKey,
}: {
  id: string;            // anchor target for the jump nav (e.g. "chapter-privacy")
  number: number;        // 1, 2, …
  titleKey: string;      // i18n key for chapter title
  refKey: string;        // i18n key for article-reference subtitle
}) {
  const { t } = useLang();
  return (
    <div
      id={id}
      className="scroll-mt-20 pt-4"
    >
      <div className="border-t-2 border-primary/20" />
      <div className="mt-5">
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          {t("chapter.kicker")} {number}
        </div>
        <h2 className="mt-1 text-2xl font-bold tracking-tight">{t(titleKey)}</h2>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{t(refKey)}</p>
      </div>
    </div>
  );
}
