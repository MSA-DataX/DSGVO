"use client";

import { useRouter, usePathname } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/components/auth/AuthProvider";
import { useLang } from "@/lib/LanguageContext";

/**
 * Stricter gate than RequireAuth — the user must ALSO have
 * `is_superuser`. Non-admins authenticated users get punted back to "/"
 * (the dashboard) rather than to /login: they're already signed in,
 * they just don't belong here. The backend enforces the same check on
 * every /admin/* call; this component is UX only.
 */
export function RequireAdmin({ children }: { children: React.ReactNode }) {
  const { status, user } = useAuth();
  const { t } = useLang();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (status === "anonymous") {
      const from = encodeURIComponent(pathname || "/admin");
      router.replace(`/login?from=${from}`);
    } else if (status === "authenticated" && user && !user.is_superuser) {
      router.replace("/");
    }
  }, [status, user, router, pathname]);

  if (status === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-sm text-muted-foreground">{t("auth.loading")}</p>
      </div>
    );
  }
  if (status === "anonymous" || (user && !user.is_superuser)) {
    return null; // effect redirects; don't flash protected content
  }
  return <>{children}</>;
}
