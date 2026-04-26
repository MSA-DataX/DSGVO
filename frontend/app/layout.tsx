import type { Metadata } from "next";
import { AuthProvider } from "@/components/auth/AuthProvider";
import { LanguageProvider } from "@/lib/LanguageContext";
import "./globals.css";

export const metadata: Metadata = {
  title: "MSA DataX — GDPR Scanner",
  description: "Scan a website for GDPR compliance: cookies, trackers, data flow, privacy policy.",
  icons: {
    icon: "/favicon.png",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen bg-background font-sans antialiased">
        {/* Phase-11-design (Polish): thin brand accent at the very top
            of every page. Carries the MSA DataX teal across login,
            signup, dashboard, admin, billing — single visual element
            that ties the surfaces together. */}
        <div
          aria-hidden
          className="fixed inset-x-0 top-0 z-50 h-1 bg-gradient-to-r from-primary via-primary/70 to-primary"
        />
        <AuthProvider>
          <LanguageProvider>{children}</LanguageProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
