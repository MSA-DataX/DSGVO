"use client";

import { ShieldCheck, MapPin, EyeOff } from "lucide-react";
import { useLang } from "@/lib/LanguageContext";

// Hero-Section über dem Scan-Form. Outcome-Sprache statt Tech-Sprache:
// die H1 verkauft den Job-to-be-Done, nicht die Crawler-Pipeline. Der
// Trust-Row leveraged drei reale Differenzierungen die in CLAUDE.md
// Conventions #7 + #-passive-only verteidigt werden — § 202c StGB-
// Konformität, EU-Datenhaltung, kein Geo-IP-Leak. Diese drei Punkte
// sind keine Marketing-Floskel; sie sind im Code durchgesetzt.

export function Hero() {
  const { t } = useLang();
  return (
    <section className="border-b pb-10 pt-2">
      <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">
        {t("hero.h1")}
      </h1>
      <p className="mt-3 max-w-2xl text-base text-muted-foreground sm:text-lg">
        {t("hero.subtitle")}
      </p>
      <ul className="mt-6 flex flex-col flex-wrap gap-3 text-sm sm:flex-row sm:gap-x-6">
        <TrustItem icon={<ShieldCheck className="h-4 w-4" />} label={t("hero.trust.passive")} />
        <TrustItem icon={<MapPin className="h-4 w-4" />} label={t("hero.trust.eu")} />
        <TrustItem icon={<EyeOff className="h-4 w-4" />} label={t("hero.trust.noGeoIp")} />
      </ul>
    </section>
  );
}

function TrustItem({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <li className="flex items-center gap-2 text-muted-foreground">
      <span className="text-primary">{icon}</span>
      <span>{label}</span>
    </li>
  );
}
