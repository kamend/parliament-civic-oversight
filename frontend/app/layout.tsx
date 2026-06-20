import type { Metadata } from "next";
import { Bitter, Golos_Text, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

// Slab serif, drawn for the screen — display + reading type. The slab reads as
// the *typed* verbatim record (a stenographer's page), not a literary magazine.
// Full Cyrillic.
const bitter = Bitter({
  variable: "--font-display",
  subsets: ["latin", "cyrillic"],
  weight: ["400", "500", "600", "700", "800"],
  style: ["normal", "italic"],
});

// Cyrillic-native public-sector sans for UI chrome. "Голос" = voice / vote —
// the right register for a civic-oversight instrument.
const golos = Golos_Text({
  variable: "--font-sans",
  subsets: ["latin", "cyrillic"],
  weight: ["400", "500", "600", "700"],
});

// Mono for record metadata, scores, source numbers — the "apparatus" voice.
const plexMono = IBM_Plex_Mono({
  variable: "--font-mono",
  subsets: ["latin", "cyrillic"],
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "Граждански контрол",
  description:
    "Задавайте въпроси за дебатите в Народното събрание и получавайте ясни " +
    "отговори, опрени на официалните стенограми.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="bg"
      className={`${bitter.variable} ${golos.variable} ${plexMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
