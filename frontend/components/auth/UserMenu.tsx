"use client";

import * as React from "react";
import Link from "next/link";
import { ChevronDown, LogOut, CreditCard, Shield } from "lucide-react";
import { useAuth } from "@/components/auth/AuthProvider";
import { useLang } from "@/lib/LanguageContext";

// Avatar + Dropdown. Avatar ist die User-Initiale auf einem Brand-Tinted
// Disk (kein externer Image-Service — siehe CLAUDE.md #7 Geist). Klick
// öffnet ein Mini-Dropdown mit Email-Header + Abrechnung + (Admin) +
// Abmelden. Wir bauen das Dropdown selbst statt shadcn dropdown-menu zu
// installieren, um die "no new deps"-Regel des Polish-Sprints zu halten.
export function UserMenu() {
  const { user, logout } = useAuth();
  const { t } = useLang();
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!open) return;
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function handleEsc(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleEsc);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEsc);
    };
  }, [open]);

  if (!user) return null;
  const initial = (user.display_name || user.email || "?").trim().charAt(0).toUpperCase();
  const labelEmail = user.display_name || user.email;

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex items-center gap-2 rounded-full border bg-background px-1.5 py-1 text-sm transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        title={user.email}
      >
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/15 text-xs font-semibold text-primary">
          {initial}
        </span>
        <ChevronDown className="mr-1 h-3.5 w-3.5 text-muted-foreground" />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 z-50 mt-2 w-56 overflow-hidden rounded-md border bg-card shadow-lg"
        >
          <div className="border-b px-3 py-2 text-xs">
            <div className="font-medium">{user.display_name || ""}</div>
            <div className="truncate text-muted-foreground">{user.email}</div>
          </div>
          <DropdownLink href="/billing" icon={<CreditCard className="h-3.5 w-3.5" />} onClick={() => setOpen(false)}>
            {t("auth.billingLink")}
          </DropdownLink>
          {user.is_superuser && (
            <DropdownLink href="/admin" icon={<Shield className="h-3.5 w-3.5" />} onClick={() => setOpen(false)}>
              {t("auth.adminLink")}
            </DropdownLink>
          )}
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              logout();
            }}
            className="flex w-full items-center gap-2 border-t px-3 py-2 text-left text-sm text-risk-high hover:bg-accent"
          >
            <LogOut className="h-3.5 w-3.5" />
            {t("auth.logout")}
          </button>
        </div>
      )}
      {/* Visible-only on sm+: email next to the avatar so the user
          recognises who they're signed in as without opening the menu. */}
      <span className="sr-only">{labelEmail}</span>
    </div>
  );
}

function DropdownLink({
  href, icon, onClick, children,
}: {
  href: string;
  icon: React.ReactNode;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      role="menuitem"
      onClick={onClick}
      className="flex items-center gap-2 px-3 py-2 text-sm hover:bg-accent"
    >
      {icon}
      {children}
    </Link>
  );
}
