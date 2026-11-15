import type { Metadata } from "next";
import type { ReactNode } from "react";
import { DM_Mono, DM_Sans } from "next/font/google";
import "./globals.css";

const dmSans = DM_Sans({
  variable: "--font-orbit-sans",
  subsets: ["latin"],
});

const dmMono = DM_Mono({
  variable: "--font-orbit-mono",
  weight: ["400", "500"],
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "OrbitFarm | Climate Field Lab",
  description: "Исторические данные NASA POWER и сопоставление климатических факторов участка для десяти культур.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ru" className={`${dmSans.variable} ${dmMono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
