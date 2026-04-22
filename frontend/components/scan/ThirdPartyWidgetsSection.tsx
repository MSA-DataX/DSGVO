"use client";

import * as React from "react";
import {
  Youtube, Map as MapIcon, MessageSquare, LogIn, Share2,
  ChevronDown, ChevronRight, Shield, ShieldAlert,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { countryColor } from "@/lib/utils";
import type {
  ThirdPartyWidget, ThirdPartyWidgetsReport, WidgetCategory, WidgetKind,
} from "@/lib/types";

// Rendering rationale: four categories with very different fixes should
// look visually distinct. Videos & maps → "switch variant". Chat →
// "gate behind consent". Auth → "load lazily". The summary line on top
// highlights the one that matters most — tracking-variant videos — since
// they're the cheapest to fix (swap hostname) and most common finding.

const CATEGORY_LABEL: Record<WidgetCategory, string> = {
  video:        "Video embeds",
  map:          "Map embeds",
  chat:         "Chat widgets",
  auth:         "Social-login SDKs",
  social_embed: "Social embeds",
  other:        "Other widgets",
};

const CATEGORY_ORDER: WidgetCategory[] = [
  "video", "map", "chat", "auth", "social_embed", "other",
];

function iconForCategory(c: WidgetCategory) {
  switch (c) {
    case "video":        return <Youtube className="h-4 w-4" />;
    case "map":          return <MapIcon className="h-4 w-4" />;
    case "chat":         return <MessageSquare className="h-4 w-4" />;
    case "auth":         return <LogIn className="h-4 w-4" />;
    case "social_embed": return <Share2 className="h-4 w-4" />;
    default:             return <Share2 className="h-4 w-4" />;
  }
}

const KIND_NAME: Partial<Record<WidgetKind, string>> = {
  youtube:            "YouTube",
  youtube_nocookie:   "YouTube (nocookie)",
  vimeo:              "Vimeo",
  vimeo_dnt:          "Vimeo (DNT)",
  wistia:             "Wistia",
  google_maps:        "Google Maps",
  openstreetmap:      "OpenStreetMap",
  mapbox:             "Mapbox",
  bing_maps:          "Bing Maps",
  chat_intercom:      "Intercom",
  chat_drift:         "Drift",
  chat_zendesk:       "Zendesk",
  chat_tawk:          "Tawk.to",
  chat_crisp:         "Crisp",
  chat_livechat:      "LiveChat",
  chat_hubspot:       "HubSpot",
  chat_facebook:      "Messenger Customer Chat",
  auth_google:        "Sign in with Google",
  auth_facebook:      "Facebook Login",
  auth_apple:         "Sign in with Apple",
  auth_microsoft:     "Microsoft Identity",
  auth_linkedin:      "LinkedIn Auth",
  auth_twitter:       "X/Twitter Auth",
  auth_github:        "GitHub OAuth",
  twitter_widget:     "X/Twitter Widget",
  facebook_widget:    "Facebook Plugin",
  instagram_embed:    "Instagram Post",
  linkedin_widget:    "LinkedIn Widget",
  tiktok_embed:       "TikTok Embed",
  pinterest_widget:   "Pinterest Widget",
};

function kindLabel(k: WidgetKind): string {
  return KIND_NAME[k] ?? k;
}

export function ThirdPartyWidgetsSection({ report }: { report: ThirdPartyWidgetsReport }) {
  const [open, setOpen] = React.useState(true);
  if (report.widgets.length === 0) return null;

  const nonEnhancedVideo = report.summary["non_enhanced_video"] ?? 0;
  const chatCount = report.summary["category_chat"] ?? 0;
  const authCount = report.summary["category_auth"] ?? 0;
  const enhanced = report.summary["privacy_enhanced"] ?? 0;

  // group by category for rendering
  const grouped = groupByCategory(report.widgets);

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
              <Share2 className="h-5 w-5" />
              Third-party widgets
            </CardTitle>
            <CardDescription>
              {report.widgets.length} widget(s) embedded on the site —{" "}
              {nonEnhancedVideo} tracking-variant video(s), {chatCount} chat,{" "}
              {authCount} social-login SDK(s), {enhanced} privacy-enhanced.
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
          {CATEGORY_ORDER.map((cat) => {
            const items = grouped.get(cat);
            if (!items || items.length === 0) return null;
            return <CategoryBlock key={cat} category={cat} items={items} />;
          })}
        </CardContent>
      )}
    </Card>
  );
}

function groupByCategory(widgets: ThirdPartyWidget[]): Map<WidgetCategory, ThirdPartyWidget[]> {
  const m = new Map<WidgetCategory, ThirdPartyWidget[]>();
  for (const w of widgets) {
    const a = m.get(w.category) ?? [];
    a.push(w);
    m.set(w.category, a);
  }
  return m;
}

function CategoryBlock({
  category,
  items,
}: {
  category: WidgetCategory;
  items: ThirdPartyWidget[];
}) {
  return (
    <div className="rounded-md border p-3">
      <div className="mb-2 flex items-center gap-2">
        {iconForCategory(category)}
        <span className="text-sm font-medium">{CATEGORY_LABEL[category]}</span>
        <span className="text-xs text-muted-foreground">({items.length})</span>
      </div>
      <ul className="space-y-2">
        {items.map((w, i) => (
          <li key={i} className="flex flex-wrap items-center gap-2 text-xs">
            <Badge variant="outline" className="text-[10px]">{kindLabel(w.kind)}</Badge>
            {w.vendor && (
              <span className="text-muted-foreground">{w.vendor}</span>
            )}
            <Badge className={`text-[10px] uppercase ${countryColor(w.country)}`}>
              {w.country}
            </Badge>
            {w.privacy_enhanced ? (
              <Badge className="bg-risk-low/10 text-risk-low text-[10px]">
                <Shield className="mr-1 h-3 w-3" />
                privacy-enhanced
              </Badge>
            ) : w.requires_consent ? (
              <Badge className="bg-risk-high/10 text-risk-high text-[10px]">
                <ShieldAlert className="mr-1 h-3 w-3" />
                tracking variant
              </Badge>
            ) : null}
            <code className="flex-1 min-w-0 break-all font-mono text-[11px] text-muted-foreground">
              {w.src}
            </code>
            <span className="text-[10px] text-muted-foreground">
              on {w.pages.length || 0} page{w.pages.length === 1 ? "" : "s"}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
