import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";

const geistSans = localFont({
  src: "./fonts/GeistVF.woff",
  variable: "--font-geist-sans",
  weight: "100 900",
});
const geistMono = localFont({
  src: "./fonts/GeistMonoVF.woff",
  variable: "--font-geist-mono",
  weight: "100 900",
});

export const metadata: Metadata = {
  title: "StoryForge",
  description: "Long-form AI fiction generation",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased bg-white text-gray-900`}
      >
        <nav className="border-b border-gray-200 px-6 py-3 flex items-center gap-6">
          <a href="/" className="text-lg font-bold tracking-tight text-indigo-700">
            StoryForge
          </a>
          <a
            href="/generate"
            className="text-sm font-medium text-gray-600 hover:text-gray-900"
          >
            Generate
          </a>
        </nav>
        {children}
      </body>
    </html>
  );
}
