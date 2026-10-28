import type { Metadata, Viewport } from "next";

import { Nav } from "@/components/Nav";

import "./globals.css";

export const metadata: Metadata = {
  title: "JobMatch",
  description: "Resume-aware job finder and ATS coach",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen font-sans antialiased">
        <Nav />
        <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
