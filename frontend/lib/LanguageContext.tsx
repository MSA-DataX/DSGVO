"use client";

import * as React from "react";
import { translate, type Lang } from "./i18n";

// localStorage key kept short — no namespace needed since we only store
// the language preference.
const STORAGE_KEY = "msadatax.lang";

type LangContextValue = {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: string, vars?: Record<string, string | number>) => string;
};

const LangContext = React.createContext<LangContextValue | null>(null);

function detectInitialLang(): Lang {
  // SSR-safe: return a stable default when window is unavailable. We
  // re-read localStorage in the client-side effect below so the user's
  // saved preference wins on hydration.
  if (typeof window === "undefined") return "en";
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === "de" || saved === "en") return saved;
  } catch {
    // localStorage can be disabled; fall through
  }
  // Respect browser preference on first visit.
  const nav = window.navigator.language || "en";
  return nav.toLowerCase().startsWith("de") ? "de" : "en";
}

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  // Start in "en" during SSR + initial hydration to avoid mismatch, then
  // swap to the detected language in an effect. This flash is tolerable
  // (one render) and keeps Next happy.
  const [lang, setLangState] = React.useState<Lang>("en");

  React.useEffect(() => {
    setLangState(detectInitialLang());
  }, []);

  const setLang = React.useCallback((l: Lang) => {
    setLangState(l);
    try {
      window.localStorage.setItem(STORAGE_KEY, l);
    } catch {
      // ignore
    }
  }, []);

  const t = React.useCallback(
    (key: string, vars?: Record<string, string | number>) => translate(lang, key, vars),
    [lang],
  );

  const value = React.useMemo<LangContextValue>(
    () => ({ lang, setLang, t }),
    [lang, setLang, t],
  );

  return <LangContext.Provider value={value}>{children}</LangContext.Provider>;
}

export function useLang(): LangContextValue {
  const ctx = React.useContext(LangContext);
  if (ctx === null) {
    // Graceful fallback so a component used outside the provider still
    // renders something meaningful (useful in PDF renderer contexts).
    return {
      lang: "en",
      setLang: () => {},
      t: (key, vars) => translate("en", key, vars),
    };
  }
  return ctx;
}
