import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'FinAnalyse - Institutional-grade financial analysis, automated',
  description: 'Upload an annual report PDF. Get a 19-sheet Excel model, AI investment commentary, and 6 analyst recommendations in minutes.',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=DM+Sans:ital,opsz,wght@0,9..40,100..1000;1,9..40,100..1000&family=JetBrains+Mono:wght@400;500&display=swap"
          rel="stylesheet"
        />
      </head>
      <body style={{ fontFamily: "'DM Sans', sans-serif" }}>
        {/* Floating background particles */}
        {Array.from({ length: 20 }).map((_, i) => (
          <div
            key={i}
            className="particle"
            style={{
              left: `${(i * 17 + 7) % 100}%`,
              top: `${(i * 23 + 11) % 100}%`,
              animationDelay: `${(i * 0.7) % 8}s`,
              animationDuration: `${14 + (i * 3) % 16}s`,
            }}
          />
        ))}

        {/* Floating geometric shapes */}
        <div className="geo-shape shape-1" />
        <div className="geo-shape shape-2" />
        <div className="geo-shape shape-3" />

        {children}
      </body>
    </html>
  )
}
