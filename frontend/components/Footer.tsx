import type { ReactNode } from "react";

/**
 * Site footer. Always carries the public-information disclaimer; an optional
 * page-specific line (a tagline or back-link) renders above it via `children`.
 */
export function Footer({ children }: { children?: ReactNode }) {
  return (
    <footer className="relative z-10 border-t border-line px-6 py-5 text-center font-mono text-[0.62rem] text-ink-faint">
      <div className="mx-auto flex max-w-[1400px] flex-col items-center gap-3">
        {children && <div>{children}</div>}
        <p className="max-w-3xl font-sans text-[0.68rem] leading-relaxed text-ink-faint/90">
          Цялата информация на този сайт е с обществен характер и е събрана от
          публично достъпни източници, сред които и Народното събрание на
          Република България. На основание чл. 4, ал. 1 и ал. 3 от Закона за
          достъп до обществена информация, право на достъп до тези данни имат
          всички граждани и юридически лица в Република България.
        </p>
      </div>
    </footer>
  );
}
