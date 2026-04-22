import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

import type { CookieCategory, RiskRating, Severity } from "./types";

export function ratingColor(rating: RiskRating): string {
  switch (rating) {
    case "low": return "text-risk-low border-risk-low";
    case "medium": return "text-risk-medium border-risk-medium";
    case "high": return "text-risk-high border-risk-high";
    case "critical": return "text-risk-critical border-risk-critical";
  }
}

export function ratingBg(rating: RiskRating): string {
  switch (rating) {
    case "low": return "bg-risk-low/10 text-risk-low";
    case "medium": return "bg-risk-medium/10 text-risk-medium";
    case "high": return "bg-risk-high/10 text-risk-high";
    case "critical": return "bg-risk-critical/10 text-risk-critical";
  }
}

export function severityColor(s: Severity): string {
  return ratingBg(s as RiskRating);
}

export function categoryColor(c: CookieCategory): string {
  switch (c) {
    case "necessary":  return "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400";
    case "functional": return "bg-sky-500/10 text-sky-700 dark:text-sky-400";
    case "analytics":  return "bg-amber-500/10 text-amber-700 dark:text-amber-400";
    case "marketing":  return "bg-rose-500/10 text-rose-700 dark:text-rose-400";
    case "unknown":    return "bg-slate-500/10 text-slate-600 dark:text-slate-400";
  }
}

export function countryColor(c: string): string {
  switch (c) {
    case "EU":      return "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400";
    case "USA":     return "bg-rose-500/10 text-rose-700 dark:text-rose-400";
    case "Other":   return "bg-orange-500/10 text-orange-700 dark:text-orange-400";
    default:        return "bg-slate-500/10 text-slate-600 dark:text-slate-400";
  }
}
