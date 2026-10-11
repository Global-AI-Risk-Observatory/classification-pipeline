import type { Metadata } from "next";
import { Onest } from "next/font/google";
import { PageNav } from "@/components/page-nav";
import "./globals.css";

const onest = Onest({
  variable: "--font-onest",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "AI Risk Observatory | US filings",
  description: "AI and tech regulation events against the US 10-K filing corpus",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${onest.variable} antialiased bg-background text-foreground min-h-screen flex flex-col`}>
        <PageNav />
        <main className="flex-1">{children}</main>
        <footer className="border-t border-border bg-white">
          <div className="mx-auto max-w-7xl px-6 py-6 text-xs text-muted-foreground">
            AI Risk Observatory, US filings. Data: gs://airo-pipeline-data/us-2025h1. Code:{" "}
            <a href="https://github.com/Global-AI-Risk-Observatory/classification-pipeline" className="underline">
              Global-AI-Risk-Observatory/classification-pipeline
            </a>
          </div>
        </footer>
      </body>
    </html>
  );
}
