"use client";

import Link from "next/link";
import { useAuth } from "@/components/auth/AuthProvider";
import { useLang } from "@/lib/LanguageContext";
import { Button } from "@/components/ui/button";

/** Small email + sign-out control. Matches the visual weight of
 *  LanguageSwitcher so the two sit side by side in the header.
 *  Admins also see an "Admin" link to /admin. */
export function UserMenu() {
  const { user, logout } = useAuth();
  const { t } = useLang();

  if (!user) return null;

  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="hidden text-muted-foreground sm:inline" title={user.email}>
        {user.display_name || user.email}
      </span>
      <Link
        href="/billing"
        className="rounded-md border px-2 py-1 text-xs font-medium hover:bg-accent"
      >
        {t("auth.billingLink")}
      </Link>
      {user.is_superuser && (
        <Link
          href="/admin"
          className="rounded-md border px-2 py-1 text-xs font-medium hover:bg-accent"
        >
          {t("auth.adminLink")}
        </Link>
      )}
      <Button variant="outline" size="sm" onClick={() => logout()}>
        {t("auth.logout")}
      </Button>
    </div>
  );
}
