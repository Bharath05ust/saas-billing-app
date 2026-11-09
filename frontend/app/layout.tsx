import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "UST | Financial Insights",
  description: "UST Code Mode turns financial questions into sandboxed, data-driven analysis.",
  icons: {
    icon: "/ust-logo.png",
    apple: "/ust-logo.png",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
