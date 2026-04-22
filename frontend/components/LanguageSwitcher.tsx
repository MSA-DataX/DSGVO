"use client";

import { Globe } from "lucide-react";
import { LANGS } from "@/lib/i18n";
import { useLang } from "@/lib/LanguageContext";

export function LanguageSwitcher() {
  const { lang, setLang } = useLang();
  return (
    <label className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
      <Globe className="h-3.5 w-3.5" />
      <select
        value={lang}
        onChange={(e) => setLang(e.target.value as "en" | "de")}
        className="bg-transparent text-xs font-medium text-foreground outline-none"
        aria-label="Language"
      >
        {LANGS.map((l) => (
          <option key={l.code} value={l.code}>
            {l.native}
          </option>
        ))}
      </select>
    </label>
  );
}
