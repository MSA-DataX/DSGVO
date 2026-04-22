// Two-language dictionary + useT hook. Deliberately zero-dependency:
// next-intl/i18next would pull in routing concerns we don't need for a
// single-page client app. Keys are flat strings (no nested namespaces)
// because grep-ability wins over hierarchy at this size.
//
// Scope decision: we translate UI chrome (section titles, buttons, form
// labels, severity/category badges). We do NOT translate backend-
// generated prose (AI summaries, recommendation bodies) — the backend
// currently produces those in English for the `summary` / `description`
// fields. `suggested_text` drafts already match the policy's own
// language. Full backend localisation is a later pass.

export type Lang = "en" | "de";

export const LANGS: { code: Lang; label: string; native: string }[] = [
  { code: "en", label: "English",  native: "English" },
  { code: "de", label: "German",   native: "Deutsch" },
];

type Dict = Record<string, string>;

const EN: Dict = {
  // app
  "app.title":       "GDPR Compliance Scanner",
  "app.subtitle":    "Crawler · network capture · cookie analysis · AI privacy review · risk score.",

  // scan form
  "form.url":                "Website URL",
  "form.depth":              "Depth",
  "form.maxPages":           "Max pages",
  "form.scan":               "Scan",
  "form.scanning":           "Scanning…",
  "form.consentSim.title":   "Consent simulation",
  "form.consentSim.desc":    "run a second crawl that clicks “Accept all” first. Reveals which trackers are gated behind consent. Doubles scan time.",
  "form.advanced":           "Advanced options",
  "form.privacyUrl.label":   "Privacy policy URL (optional override)",
  "form.privacyUrl.hint":    "If set, skips automatic detection and uses this URL directly. Useful when the link is buried in a lazy-loaded footer and the crawler misses it. Leave empty for auto-detection.",

  // risk score card
  "risk.title":              "GDPR risk score",
  "risk.of100":              "/ 100",
  "risk.rating.low":         "Low risk",
  "risk.rating.medium":      "Medium risk",
  "risk.rating.high":        "High risk",
  "risk.rating.critical":    "Critical risk",
  "risk.cappedHint":         "Weighted sub-score average was {weighted} — final score capped by {count} hard cap(s).",

  // sub-scores
  "sub.title":               "Sub-scores",
  "sub.name.cookies":        "Cookies",
  "sub.name.tracking":       "Tracking & web storage",
  "sub.name.data_transfer":  "Data transfer",
  "sub.name.privacy":        "Privacy policy",
  "sub.name.forms":          "Forms",
  "sub.weight":              "weight {pct}% · contributes {value}",

  // hard caps
  "caps.title":              "Hard caps applied",
  "caps.maxScore":           "max score {value}",

  // recommendations
  "recs.title":              "Recommendations",
  "recs.empty":              "No actions recommended — site looks compliant.",
  "recs.priority.high":      "High",
  "recs.priority.medium":    "Medium",
  "recs.priority.low":       "Low",

  // data flow
  "flow.title":              "Data flow",
  "flow.desc":               "Third-party domains the site contacted ({count} unique).",
  "flow.empty":              "No third-party requests observed.",
  "flow.h.domain":           "Domain",
  "flow.h.country":          "Country",
  "flow.h.risk":             "Risk",
  "flow.h.categories":       "Categories",
  "flow.h.requests":         "Requests",

  // cookies
  "cookies.title":           "Cookies & Web Storage",
  "cookies.desc":            "{total} cookies ({thirdParty} third-party, {session} session-only) · {storage} storage entries",
  "cookies.tab.cookies":     "Cookies",
  "cookies.tab.storage":     "Storage",
  "cookies.h.name":          "Name",
  "cookies.h.domain":        "Domain",
  "cookies.h.category":      "Category",
  "cookies.h.vendor":        "Vendor",
  "cookies.h.reason":        "Reason",
  "cookies.h.key":           "Key",
  "cookies.h.kind":          "Kind",
  "cookies.empty":           "Nothing to show.",
  "cookies.thirdParty":      "3rd-party",

  // categories
  "category.necessary":      "necessary",
  "category.functional":     "functional",
  "category.analytics":      "analytics",
  "category.marketing":      "marketing",
  "category.unknown":        "unknown",

  // severity
  "severity.high":           "high",
  "severity.medium":         "medium",
  "severity.low":            "low",

  // privacy analysis
  "privacy.title":           "Privacy policy analysis",
  "privacy.noPolicy":        "No privacy policy was located.",
  "privacy.noAi":            "no AI provider",
  "privacy.aiFailedTitle":   "AI analysis incomplete",
  "privacy.summary":         "Summary",
  "privacy.coverage":        "Required GDPR sections",
  "privacy.issues":          "Issues ({count})",
  "privacy.charsSent":       "Sent {chars} chars of policy text to the model.",
  "privacy.draft.title":     "Draft policy text — legal review required",
  "privacy.draft.disclaimerTitle": "This is an AI-generated draft, not legal advice.",
  "privacy.draft.disclaimerBody":  "The text below is a starting point to close the finding above. It must be reviewed and adapted by qualified legal counsel before being published. MSA DataX does not guarantee legal sufficiency and assumes no liability for its use.",
  "privacy.draft.copy":      "Copy draft",
  "privacy.draft.copied":    "Copied",
  "privacy.draft.show":      "show",
  "privacy.draft.hide":      "hide",

  // forms section
  "forms.title":             "Forms",
  "forms.empty":             "No forms detected on the crawled pages.",
  "forms.desc":              "{total} form(s) — {pii} collect personal data, {consent} have a consent checkbox, {link} link to the privacy policy.",
  "forms.searchExcluded":    " · {search} search, {auth} auth (excluded from PII counts)",
  "forms.purpose.collection":"collection",
  "forms.purpose.search":    "search",
  "forms.purpose.authentication": "auth",
  "forms.purpose.unknown":   "unknown",
  "forms.field.consent":     "Consent checkbox",
  "forms.field.privacy":     "Privacy link",
  "forms.action":            "Action",
  "forms.data":              "Data collected",
  "forms.legal":             "Legal text excerpt",
  "forms.ok":                "OK",
  "forms.issues":            "{count} issue(s)",

  // consent section
  "consent.title":           "Consent simulation",
  "consent.noBanner.title":  "No banner clicked",
  "consent.noBanner.desc":   "Either the site has no cookie banner, or our detection didn't recognize it. The pre/post diff below is unlikely to be meaningful.",
  "consent.clean.title":     "No additional tracking after consent",
  "consent.clean.desc":      "Clicking “Accept all” triggered no new cookies, storage entries, or third-party requests. Either the site does no tracking, or it was already loading everything pre-consent (which would be a separate finding).",
  "consent.stat.newCookies": "New cookies",
  "consent.stat.newStorage": "New storage",
  "consent.stat.newDomains": "New domains",
  "consent.stat.extraReq":   "Extra requests",
  "consent.pre":             "Pre-consent",
  "consent.post":            "Post-consent",
  "consent.ux.clean.title":  "Consent banner UX looks clean",
  "consent.ux.clean.desc":   "Accept and Reject buttons are present at the same level, comparable in size and prominence. No dark patterns detected.",
  "consent.ux.dark.title":   "Consent banner dark patterns ({count})",
  "consent.ux.acceptBtn":    "Accept button",
  "consent.ux.rejectBtn":    "Reject button",

  // contact channels
  "channels.title":          "Contact channels",
  "channels.desc":           "{count} exposed channel(s) — {us} route data outside the EU/EEA, {unknown} to an unknown jurisdiction. Each non-EU channel must be named + legally justified in the privacy policy (Art. 13 + third-country safeguards).",
  "channels.detected":       "{n}× detected",
  "channels.onPages":        "on {count} page(s)",

  // widgets
  "widgets.title":           "Third-party widgets",
  "widgets.desc":            "{total} widget(s) embedded on the site — {video} tracking-variant video(s), {chat} chat, {auth} social-login SDK(s), {enhanced} privacy-enhanced.",
  "widgets.cat.video":       "Video embeds",
  "widgets.cat.map":         "Map embeds",
  "widgets.cat.chat":        "Chat widgets",
  "widgets.cat.auth":        "Social-login SDKs",
  "widgets.cat.social_embed":"Social embeds",
  "widgets.cat.other":       "Other widgets",
  "widgets.tag.enhanced":    "privacy-enhanced",
  "widgets.tag.tracking":    "tracking variant",
  "widgets.onPages":         "on {count} page(s)",

  // security audit
  "security.title":          "Security audit",
  "security.desc":           "Passive check: HTTP headers, TLS, mixed content. {high} critical, {medium} medium issue(s).{mixed}",
  "security.mixed":          " {count} mixed-content request(s).",
  "security.tls.httpsEnforced": "HTTPS enforced",
  "security.tls.version":    "TLS version",
  "security.tls.certExpires":"Cert expires",
  "security.tls.hsts":       "HSTS",
  "security.tls.yes":        "yes",
  "security.tls.noHttp":     "NO — plain HTTP reachable",
  "security.tls.unknown":    "unknown",
  "security.tls.in":         "in {days}d",
  "security.tls.ago":        "{days}d AGO",
  "security.tls.missing":    "missing",
  "security.tls.preloadReady": " · preload-ready",
  "security.mixedTitle":     "{count} mixed-content request(s)",
  "security.mixedDesc":      "HTTPS page loads resource(s) over plain HTTP. Browser padlock is misleading — transport encryption only protects the shell, not the loaded assets.",
  "security.h.header":       "Header",
  "security.h.status":       "Status",
  "security.h.severity":     "Severity if missing",
  "security.h.note":         "Note",
  "security.header.present": "present",
  "security.header.missing": "missing",
  "security.infoLeak.title": "Information leak in response headers",
  "security.footer":         "All checks are passive (same info any browser visit reveals). No active probing, no directory bruteforce, no exploit attempts — compliant with § 202c StGB.",
  "security.error":          "Audit could not complete:",

  // Phase 5 — DNS / security.txt / SRI
  "security.dns.title":      "DNS hardening",
  "security.dns.spf":        "SPF",
  "security.dns.dmarc":      "DMARC",
  "security.dns.dnssec":     "DNSSEC",
  "security.dns.caa":        "CAA",
  "security.dns.present":    "present",
  "security.dns.missing":    "missing",
  "security.dns.policy":     "policy",
  "security.sri.title":      "Subresource Integrity",
  "security.sri.missing":    "{count} cross-origin script(s) without integrity hash",
  "security.sri.ok":         "All cross-origin scripts use Subresource Integrity",
  "security.securityTxt.title":   "security.txt",
  "security.securityTxt.present": "published",
  "security.securityTxt.missing": "missing (RFC 9116 best practice)",

  // Vulnerable libraries
  "vulnLibs.title":          "Known-vulnerable JavaScript libraries",
  "vulnLibs.desc":           "{total} finding(s) — {high} high, {medium} medium, {low} low severity.",
  "vulnLibs.empty":          "No libraries with known vulnerabilities detected.",
  "vulnLibs.h.lib":          "Library",
  "vulnLibs.h.version":      "Detected",
  "vulnLibs.h.severity":     "Severity",
  "vulnLibs.h.fixed":        "Fixed in",
  "vulnLibs.h.cves":         "CVE(s)",
  "vulnLibs.h.advisory":     "Advisory",

  // first-party scripts
  "firstParty.title":        "First-party assets",
  "firstParty.desc":         "{count} unique URL(s) loaded from your own origin — {scripts} script(s), {styles} stylesheet(s), {apis} XHR/fetch call(s). Useful for documentation and for catching what external “beacon” scanners misattribute to third parties.",
  "firstParty.h.type":       "Type",
  "firstParty.h.url":        "URL",
  "firstParty.h.requests":   "Requests",

  // progress
  "progress.started":        "Started",
  "progress.crawling":       "Crawling pages",
  "progress.cookie":         "Cookies & web storage",
  "progress.policy":         "Privacy policy text",
  "progress.ai":             "AI policy review",
  "progress.forms":          "Forms",
  "progress.scoring":        "Risk scoring",
  "progress.starting":       "Starting…",
  "progress.failed":         "Scan failed",

  // export
  "export.json":             "Export JSON",
  "export.pdf":              "Export PDF",
  "export.generating":       "Generating…",

  // history
  "history.title":           "Scan history",
  "history.count":           "{count} recent scan(s)",
  "history.empty":           "No scans yet. Run one above.",
  "history.loading":         "Loading…",

  // common
  "common.scanId":           "Scan",

  // Chapters + jump nav
  "chapter.kicker":          "Chapter",
  "chapter.privacy.title":   "GDPR / Privacy",
  "chapter.privacy.ref":     "Articles 5, 6, 13, 25 GDPR · findings about data processing, consent, and transparency.",
  "chapter.security.title":  "Security & Art. 32 GDPR (TOM)",
  "chapter.security.ref":    "Technical & organisational measures · passive observations of transport encryption, headers, DNS, vulnerable libraries.",
  "nav.jumpTo":              "Jump to",
  "nav.overview":            "Overview",
  "nav.privacy":             "Privacy",
  "nav.security":            "Security",
};

const DE: Dict = {
  // app
  "app.title":       "DSGVO Compliance Scanner",
  "app.subtitle":    "Crawler · Netzwerk · Cookies · KI-Datenschutzprüfung · Risiko-Score.",

  // scan form
  "form.url":                "Webseiten-URL",
  "form.depth":              "Tiefe",
  "form.maxPages":           "Max. Seiten",
  "form.scan":               "Scan",
  "form.scanning":           "Scanne…",
  "form.consentSim.title":   "Consent-Simulation",
  "form.consentSim.desc":    "zweiter Durchlauf nach Klick auf \"Alle akzeptieren\". Zeigt welche Tracker hinter Consent gegated sind. Verdoppelt Scan-Zeit.",
  "form.advanced":           "Erweiterte Optionen",
  "form.privacyUrl.label":   "Datenschutz-URL (optional manuell überschreiben)",
  "form.privacyUrl.hint":    "Falls gesetzt, überspringt die Auto-Erkennung und verwendet diese URL direkt. Hilfreich wenn der Link im Footer lazy geladen wird und der Crawler ihn verpasst. Leer lassen für Auto-Erkennung.",

  // risk score
  "risk.title":              "DSGVO-Risiko-Score",
  "risk.of100":              "/ 100",
  "risk.rating.low":         "Niedriges Risiko",
  "risk.rating.medium":      "Mittleres Risiko",
  "risk.rating.high":        "Hohes Risiko",
  "risk.rating.critical":    "Kritisches Risiko",
  "risk.cappedHint":         "Gewichteter Sub-Score-Mittelwert war {weighted} — Finalwert durch {count} Hard-Cap(s) begrenzt.",

  // sub-scores
  "sub.title":               "Sub-Scores",
  "sub.name.cookies":        "Cookies",
  "sub.name.tracking":       "Tracking & Web-Storage",
  "sub.name.data_transfer":  "Datenübermittlung",
  "sub.name.privacy":        "Datenschutzerklärung",
  "sub.name.forms":          "Formulare",
  "sub.weight":              "Gewicht {pct}% · Beitrag {value}",

  // hard caps
  "caps.title":              "Angewandte Hard-Caps",
  "caps.maxScore":           "max. Score {value}",

  // recs
  "recs.title":              "Empfehlungen",
  "recs.empty":              "Keine Maßnahmen erforderlich — Seite wirkt konform.",
  "recs.priority.high":      "Hoch",
  "recs.priority.medium":    "Mittel",
  "recs.priority.low":       "Niedrig",

  // data flow
  "flow.title":              "Datenfluss",
  "flow.desc":               "Drittanbieter-Domains mit Kontakt ({count} einzigartig).",
  "flow.empty":              "Keine Drittanbieter-Requests beobachtet.",
  "flow.h.domain":           "Domain",
  "flow.h.country":          "Land",
  "flow.h.risk":             "Risiko",
  "flow.h.categories":       "Kategorien",
  "flow.h.requests":         "Requests",

  // cookies
  "cookies.title":           "Cookies & Web-Storage",
  "cookies.desc":            "{total} Cookies ({thirdParty} Drittanbieter, {session} nur Session) · {storage} Storage-Einträge",
  "cookies.tab.cookies":     "Cookies",
  "cookies.tab.storage":     "Storage",
  "cookies.h.name":          "Name",
  "cookies.h.domain":        "Domain",
  "cookies.h.category":      "Kategorie",
  "cookies.h.vendor":        "Anbieter",
  "cookies.h.reason":        "Grund",
  "cookies.h.key":           "Schlüssel",
  "cookies.h.kind":          "Art",
  "cookies.empty":           "Nichts anzuzeigen.",
  "cookies.thirdParty":      "Drittanbieter",

  // categories
  "category.necessary":      "notwendig",
  "category.functional":     "funktional",
  "category.analytics":      "Statistik",
  "category.marketing":      "Marketing",
  "category.unknown":        "unklassifiziert",

  // severity
  "severity.high":           "hoch",
  "severity.medium":         "mittel",
  "severity.low":            "niedrig",

  // privacy
  "privacy.title":           "Datenschutzerklärung-Analyse",
  "privacy.noPolicy":        "Keine Datenschutzerklärung lokalisiert.",
  "privacy.noAi":            "Keine KI konfiguriert",
  "privacy.aiFailedTitle":   "KI-Analyse unvollständig",
  "privacy.summary":         "Zusammenfassung",
  "privacy.coverage":        "Erforderliche DSGVO-Abschnitte",
  "privacy.issues":          "Findings ({count})",
  "privacy.charsSent":       "{chars} Zeichen Policy-Text an das Modell gesendet.",
  "privacy.draft.title":     "Policy-Textentwurf — juristische Prüfung erforderlich",
  "privacy.draft.disclaimerTitle": "Dies ist ein KI-generierter Entwurf, keine Rechtsberatung.",
  "privacy.draft.disclaimerBody":  "Der Text unten ist ein Ausgangspunkt zur Behebung des oben genannten Findings. Er muss vor Veröffentlichung von qualifizierten Rechtsberatern geprüft und angepasst werden. MSA DataX gibt keine Garantie für rechtliche Eignung und übernimmt keine Haftung.",
  "privacy.draft.copy":      "Entwurf kopieren",
  "privacy.draft.copied":    "Kopiert",
  "privacy.draft.show":      "zeigen",
  "privacy.draft.hide":      "verbergen",

  // forms
  "forms.title":             "Formulare",
  "forms.empty":             "Keine Formulare auf den gecrawlten Seiten gefunden.",
  "forms.desc":              "{total} Formular(e) — {pii} erheben personenbezogene Daten, {consent} haben eine Consent-Checkbox, {link} verlinken zur Datenschutzerklärung.",
  "forms.searchExcluded":    " · {search} Suche, {auth} Auth (aus PII-Zählung ausgeschlossen)",
  "forms.purpose.collection":"Erhebung",
  "forms.purpose.search":    "Suche",
  "forms.purpose.authentication": "Auth",
  "forms.purpose.unknown":   "unbekannt",
  "forms.field.consent":     "Consent-Checkbox",
  "forms.field.privacy":     "Datenschutz-Link",
  "forms.action":            "Action",
  "forms.data":              "Erhobene Daten",
  "forms.legal":             "Rechtstext-Auszug",
  "forms.ok":                "OK",
  "forms.issues":            "{count} Finding(s)",

  // consent section
  "consent.title":           "Consent-Simulation",
  "consent.noBanner.title":  "Kein Banner geklickt",
  "consent.noBanner.desc":   "Entweder hat die Seite keinen Cookie-Banner, oder unsere Erkennung hat ihn nicht identifiziert. Der Pre/Post-Diff ist vermutlich nicht aussagekräftig.",
  "consent.clean.title":     "Kein zusätzliches Tracking nach Consent",
  "consent.clean.desc":      "Klick auf \"Alle akzeptieren\" löste keine zusätzlichen Cookies, Storage oder Drittanbieter-Requests aus. Entweder macht die Seite kein Tracking, oder sie lud bereits vor Consent alles (was ein separates Finding wäre).",
  "consent.stat.newCookies": "Neue Cookies",
  "consent.stat.newStorage": "Neue Storage",
  "consent.stat.newDomains": "Neue Domains",
  "consent.stat.extraReq":   "Zusätzl. Requests",
  "consent.pre":             "Vor Consent",
  "consent.post":            "Nach Consent",
  "consent.ux.clean.title":  "Consent-Banner UX sauber",
  "consent.ux.clean.desc":   "Akzeptieren- und Ablehnen-Buttons sind auf derselben Ebene, vergleichbar in Größe und Prominenz. Keine Dark Patterns erkannt.",
  "consent.ux.dark.title":   "Consent-Banner Dark Patterns ({count})",
  "consent.ux.acceptBtn":    "Akzeptieren-Button",
  "consent.ux.rejectBtn":    "Ablehnen-Button",

  // contact channels
  "channels.title":          "Kontaktkanäle",
  "channels.desc":           "{count} offengelegte(r) Kanal(e) — {us} leiten Daten außerhalb EU/EWR, {unknown} in unbekannte Jurisdiktion. Jeder Nicht-EU-Kanal muss in der Datenschutzerklärung genannt und rechtlich begründet sein (Art. 13 + Drittland-Schutzmaßnahmen).",
  "channels.detected":       "{n}× erkannt",
  "channels.onPages":        "auf {count} Seite(n)",

  // widgets
  "widgets.title":           "Drittanbieter-Widgets",
  "widgets.desc":            "{total} eingebettete(s) Widget(s) — {video} tracking-Variante-Video(s), {chat} Chat, {auth} Social-Login-SDK(s), {enhanced} datenschutzverbessert.",
  "widgets.cat.video":       "Video-Einbettungen",
  "widgets.cat.map":         "Karten-Einbettungen",
  "widgets.cat.chat":        "Chat-Widgets",
  "widgets.cat.auth":        "Social-Login-SDKs",
  "widgets.cat.social_embed":"Social-Einbettungen",
  "widgets.cat.other":       "Sonstige Widgets",
  "widgets.tag.enhanced":    "datenschutzverbessert",
  "widgets.tag.tracking":    "Tracking-Variante",
  "widgets.onPages":         "auf {count} Seite(n)",

  // security
  "security.title":          "Security-Audit",
  "security.desc":           "Passive Prüfung: HTTP-Header, TLS, Mixed Content. {high} kritisch, {medium} mittel.{mixed}",
  "security.mixed":          " {count} Mixed-Content-Request(s).",
  "security.tls.httpsEnforced": "HTTPS erzwungen",
  "security.tls.version":    "TLS-Version",
  "security.tls.certExpires":"Zertifikat läuft ab",
  "security.tls.hsts":       "HSTS",
  "security.tls.yes":        "ja",
  "security.tls.noHttp":     "NEIN — HTTP erreichbar",
  "security.tls.unknown":    "unbekannt",
  "security.tls.in":         "in {days} T",
  "security.tls.ago":        "{days} T ABGELAUFEN",
  "security.tls.missing":    "fehlt",
  "security.tls.preloadReady": " · preload-fähig",
  "security.mixedTitle":     "{count} Mixed-Content-Request(s)",
  "security.mixedDesc":      "HTTPS-Seite lädt Ressource(n) über HTTP. Das Browser-Schloss ist irreführend — Transport-Verschlüsselung schützt nur die Shell, nicht die geladenen Assets.",
  "security.h.header":       "Header",
  "security.h.status":       "Status",
  "security.h.severity":     "Schwere bei Fehlen",
  "security.h.note":         "Hinweis",
  "security.header.present": "vorhanden",
  "security.header.missing": "fehlt",
  "security.infoLeak.title": "Information Leak in Response-Headern",
  "security.footer":         "Alle Prüfungen passiv (selbe Info die jeder Browser-Besuch offenbart). Kein aktives Probing, kein Directory-Bruteforce, keine Exploit-Versuche — konform § 202c StGB.",
  "security.error":          "Audit konnte nicht durchgeführt werden:",

  // Phase 5 — DNS / security.txt / SRI
  "security.dns.title":      "DNS-Härtung",
  "security.dns.spf":        "SPF",
  "security.dns.dmarc":      "DMARC",
  "security.dns.dnssec":     "DNSSEC",
  "security.dns.caa":        "CAA",
  "security.dns.present":    "vorhanden",
  "security.dns.missing":    "fehlt",
  "security.dns.policy":     "Policy",
  "security.sri.title":      "Subresource Integrity",
  "security.sri.missing":    "{count} Cross-Origin-Skript(e) ohne Integrity-Hash",
  "security.sri.ok":         "Alle Cross-Origin-Skripte nutzen Subresource Integrity",
  "security.securityTxt.title":   "security.txt",
  "security.securityTxt.present": "veröffentlicht",
  "security.securityTxt.missing": "fehlt (RFC-9116-Best-Practice)",

  // Verwundbare Libraries
  "vulnLibs.title":          "Bekannte verwundbare JavaScript-Libraries",
  "vulnLibs.desc":           "{total} Finding(s) — {high} hoch, {medium} mittel, {low} niedrig.",
  "vulnLibs.empty":          "Keine Libraries mit bekannten Schwachstellen erkannt.",
  "vulnLibs.h.lib":          "Library",
  "vulnLibs.h.version":      "Erkannte Version",
  "vulnLibs.h.severity":     "Schwere",
  "vulnLibs.h.fixed":        "Fix in",
  "vulnLibs.h.cves":         "CVE(s)",
  "vulnLibs.h.advisory":     "Hinweis",

  // first-party
  "firstParty.title":        "Eigene Assets",
  "firstParty.desc":         "{count} einzigartige URL(s) aus eigener Origin — {scripts} Skript(e), {styles} Stylesheet(s), {apis} XHR/fetch-Aufruf(e). Nützlich für Dokumentation und um zu sehen was externe \"Beacon\"-Scanner fälschlich als Drittanbieter ausgeben.",
  "firstParty.h.type":       "Typ",
  "firstParty.h.url":        "URL",
  "firstParty.h.requests":   "Requests",

  // progress
  "progress.started":        "Gestartet",
  "progress.crawling":       "Seiten crawlen",
  "progress.cookie":         "Cookies & Web-Storage",
  "progress.policy":         "Datenschutz-Text",
  "progress.ai":             "KI-Policy-Review",
  "progress.forms":          "Formulare",
  "progress.scoring":        "Risiko-Scoring",
  "progress.starting":       "Starte…",
  "progress.failed":         "Scan fehlgeschlagen",

  // export
  "export.json":             "JSON-Export",
  "export.pdf":              "PDF-Export",
  "export.generating":       "Erstelle…",

  // history
  "history.title":           "Scan-Historie",
  "history.count":           "{count} letzte(r) Scan(s)",
  "history.empty":           "Noch keine Scans. Starte oben einen.",
  "history.loading":         "Lade…",

  // common
  "common.scanId":           "Scan",

  // Kapitel + Sprung-Navigation
  "chapter.kicker":          "Kapitel",
  "chapter.privacy.title":   "DSGVO / Privacy",
  "chapter.privacy.ref":     "Art. 5, 6, 13, 25 DSGVO · Findings zu Datenverarbeitung, Consent und Transparenz.",
  "chapter.security.title":  "Security & Art. 32 DSGVO (TOM)",
  "chapter.security.ref":    "Technische und organisatorische Maßnahmen · passive Beobachtungen zu Transportverschlüsselung, Headern, DNS, verwundbaren Libraries.",
  "nav.jumpTo":              "Springe zu",
  "nav.overview":            "Übersicht",
  "nav.privacy":             "Privacy",
  "nav.security":            "Security",
};

const DICTS: Record<Lang, Dict> = { en: EN, de: DE };

export function translate(lang: Lang, key: string, vars?: Record<string, string | number>): string {
  const dict = DICTS[lang] ?? EN;
  let s = dict[key] ?? EN[key] ?? key;
  if (vars) {
    for (const [k, v] of Object.entries(vars)) {
      s = s.replace(new RegExp(`\\{${k}\\}`, "g"), String(v));
    }
  }
  return s;
}
