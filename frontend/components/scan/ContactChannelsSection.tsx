"use client";

import * as React from "react";
import {
  MessageCircle, Mail, Phone, Send, Facebook, Instagram, Linkedin,
  Youtube, Github, ChevronDown, ChevronRight,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { countryColor } from "@/lib/utils";
import type { ContactChannel, ContactChannelKind, ContactChannelsReport } from "@/lib/types";

// Why a dedicated section: clicking a WhatsApp button ships the user's
// phone number to Meta (US), clicking a mailto: hands it to whatever
// email provider the operator uses. These are data flows the crawler
// can't see at runtime — only reachable via HTML link inspection — so
// they need their own panel with their own policy-cross-check semantics.

const KIND_LABEL: Record<ContactChannelKind, string> = {
  whatsapp:            "WhatsApp",
  telegram:            "Telegram",
  signal:              "Signal",
  facebook_messenger:  "Messenger",
  skype:               "Skype",
  discord:             "Discord",
  email:               "Email",
  phone:               "Phone",
  sms:                 "SMS",
  facebook_profile:    "Facebook",
  instagram_profile:   "Instagram",
  linkedin_profile:    "LinkedIn",
  twitter_profile:     "X (Twitter)",
  youtube_channel:     "YouTube",
  tiktok_profile:      "TikTok",
  xing_profile:        "Xing",
  pinterest_profile:   "Pinterest",
  github_profile:      "GitHub",
};

function iconFor(kind: ContactChannelKind) {
  switch (kind) {
    case "whatsapp":
    case "telegram":
    case "signal":
    case "facebook_messenger":
    case "skype":
    case "discord":
      return <MessageCircle className="h-3.5 w-3.5" />;
    case "email":           return <Mail className="h-3.5 w-3.5" />;
    case "phone":
    case "sms":             return <Phone className="h-3.5 w-3.5" />;
    case "facebook_profile":return <Facebook className="h-3.5 w-3.5" />;
    case "instagram_profile":return <Instagram className="h-3.5 w-3.5" />;
    case "linkedin_profile":return <Linkedin className="h-3.5 w-3.5" />;
    case "youtube_channel": return <Youtube className="h-3.5 w-3.5" />;
    case "github_profile":  return <Github className="h-3.5 w-3.5" />;
    default:                return <Send className="h-3.5 w-3.5" />;
  }
}

export function ContactChannelsSection({ report }: { report: ContactChannelsReport }) {
  const [open, setOpen] = React.useState(true);
  if (report.channels.length === 0) return null;

  const grouped = groupByKind(report.channels);
  const us = report.summary["us_transfer_channels"] ?? 0;
  const unknown = report.summary["unknown_jurisdiction_channels"] ?? 0;

  return (
    <Card>
      <CardHeader>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="flex w-full items-start justify-between gap-3 text-left"
        >
          <div>
            <CardTitle className="flex items-center gap-2">
              <MessageCircle className="h-5 w-5" />
              Contact channels
            </CardTitle>
            <CardDescription>
              {report.channels.length} exposed channel(s) — {us} route data outside the EU/EEA,{" "}
              {unknown} to an unknown jurisdiction. Each non-EU channel must be named + legally
              justified in the privacy policy (Art. 13 + third-country safeguards).
            </CardDescription>
          </div>
          {open ? (
            <ChevronDown className="mt-1 h-4 w-4 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-muted-foreground" />
          )}
        </button>
      </CardHeader>
      {open && (
        <CardContent className="space-y-4">
          {grouped.map(([kind, items]) => (
            <KindBlock key={kind} kind={kind} items={items} />
          ))}
        </CardContent>
      )}
    </Card>
  );
}

function groupByKind(channels: ContactChannel[]): [ContactChannelKind, ContactChannel[]][] {
  const m = new Map<ContactChannelKind, ContactChannel[]>();
  for (const c of channels) {
    const a = m.get(c.kind) ?? [];
    a.push(c);
    m.set(c.kind, a);
  }
  // Sort: US/Other first (riskier), then EU, then Unknown
  const order = (k: ContactChannelKind) => {
    const arr = m.get(k) ?? [];
    const anyUS = arr.some((c) => c.country === "USA" || c.country === "Other");
    return anyUS ? 0 : arr.some((c) => c.country === "EU") ? 2 : 1;
  };
  return [...m.entries()].sort(([a], [b]) => order(a) - order(b));
}

function KindBlock({
  kind,
  items,
}: {
  kind: ContactChannelKind;
  items: ContactChannel[];
}) {
  const first = items[0];
  return (
    <div className="rounded-md border p-3">
      <div className="mb-2 flex items-center gap-2">
        <span className="inline-flex items-center gap-1.5 text-sm font-medium">
          {iconFor(kind)}
          {KIND_LABEL[kind]}
        </span>
        <span className="text-xs text-muted-foreground">
          {items.length}× detected
        </span>
        {first.vendor && (
          <Badge variant="outline" className="text-[10px]">
            {first.vendor}
          </Badge>
        )}
        <Badge className={`text-[10px] uppercase ${countryColor(first.country)}`}>
          {first.country}
        </Badge>
      </div>
      <ul className="space-y-1">
        {items.slice(0, 8).map((c, i) => (
          <li key={i} className="flex items-start gap-2 text-xs">
            <code className="flex-1 break-all font-mono text-[11px] text-muted-foreground">
              {c.target}
            </code>
            <span className="text-[10px] text-muted-foreground">
              on {c.pages.length} page{c.pages.length === 1 ? "" : "s"}
            </span>
          </li>
        ))}
        {items.length > 8 && (
          <li className="text-xs text-muted-foreground">
            …and {items.length - 8} more
          </li>
        )}
      </ul>
    </div>
  );
}
