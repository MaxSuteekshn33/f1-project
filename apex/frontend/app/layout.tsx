import "./globals.css";
import type { Metadata } from "next";
import { RaceProvider } from "@/lib/api";
import Shell from "@/components/Shell";

export const metadata: Metadata = { title: "APEX F1 Intelligence", description: "Race prediction, strategy optimisation and live analytics" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-sans text-[13px]">
        <RaceProvider><Shell>{children}</Shell></RaceProvider>
      </body>
    </html>
  );
}
