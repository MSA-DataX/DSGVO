"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/components/auth/AuthProvider";
import { useLang } from "@/lib/LanguageContext";
import { AuthError } from "@/lib/auth";

export default function SignupPage() {
  const { t } = useLang();
  const { status, signup } = useAuth();
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [orgName, setOrgName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (status === "authenticated") router.replace("/");
  }, [status, router]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await signup({
        email,
        password,
        display_name: displayName.trim() || undefined,
        organization_name: orgName.trim() || undefined,
      });
      router.replace("/");
    } catch (err) {
      setError(err instanceof AuthError ? err.message : t("auth.errorGeneric"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-12">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl">{t("auth.signup.title")}</CardTitle>
          <CardDescription>{t("auth.signup.subtitle")}</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="space-y-4">
            <div>
              <label className="mb-1 block text-sm font-medium" htmlFor="email">
                {t("auth.field.email")}
              </label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium" htmlFor="password">
                {t("auth.field.password")}
              </label>
              <Input
                id="password"
                type="password"
                autoComplete="new-password"
                required
                minLength={10}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              <p className="mt-1 text-xs text-muted-foreground">{t("auth.passwordHint")}</p>
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium" htmlFor="displayName">
                {t("auth.field.displayName")}
              </label>
              <Input
                id="displayName"
                autoComplete="name"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium" htmlFor="orgName">
                {t("auth.field.orgName")}
              </label>
              <Input
                id="orgName"
                autoComplete="organization"
                value={orgName}
                onChange={(e) => setOrgName(e.target.value)}
              />
            </div>

            {error && (
              <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {error}
              </div>
            )}

            <Button type="submit" disabled={submitting} className="w-full">
              {submitting ? t("auth.signup.submitting") : t("auth.signup.submit")}
            </Button>
          </form>

          <p className="mt-6 text-center text-sm text-muted-foreground">
            {t("auth.signup.haveAccount")}{" "}
            <Link href="/login" className="font-medium text-primary hover:underline">
              {t("auth.signup.loginLink")}
            </Link>
          </p>
        </CardContent>
      </Card>
    </main>
  );
}
