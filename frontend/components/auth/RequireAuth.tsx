"use client";

import { useRouter, usePathname } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/components/auth/AuthProvider";
import { useLang } from "@/lib/LanguageContext";

/**
 * Gate for pages that must have a signed-in user. While /api/auth/me is
 * resolving we render a thin "Loading…" line (not a spinner — avoids
 * layout shift and renders in ~20ms). On "anonymous" we redirect to
 * /login?from=<current-path> so the user comes back to where they were.
 */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  const { t } = useLang();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (status === "anonymous") {
      const from = encodeURIComponent(pathname || "/");
      router.replace(`/login?from=${from}`);
    }
  }, [status, router, pathname]);

  if (status === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-sm text-muted-foreground">{t("auth.loading")}</p>
      </div>
    );
  }
  if (status === "anonymous") {
    // The effect is about to redirect; render nothing to avoid flashing
    // the protected page.
    return null;
  }
  return <>{children}</>;
}
