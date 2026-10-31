// The few building blocks used everywhere: a card, a badge, and button/input styles.
// Everything follows DESIGN.md: 6px corners (rounded-md), crisp 1px borders, and spacing
// of 4px / 8px / 16px only (Tailwind 1 / 2 / 4). Cards are slightly translucent (frosted)
// so the animated background shows through.

import type { ReactNode } from "react";

export function Card({
  title,
  subtitle,
  actions,
  className = "",
  children,
}: {
  title?: ReactNode;
  subtitle?: string | null;
  actions?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  // bg-white/85 + blur: slightly see-through so the background shows, but text stays easy to read
  return (
    <section className={`rounded-md border border-slate-200 bg-white/85 backdrop-blur-sm ${className}`}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-2 border-b border-slate-200 px-4 py-2">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-ink">{title}</h2>
            {subtitle && <p className="text-xs text-slate-500">{subtitle}</p>}
          </div>
          {actions}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

// success / warning / alert are the status colours; ai is for anything the agent produced
const BADGE_TONES = {
  neutral: "bg-slate-100 text-slate-700",
  success: "bg-success/15 text-emerald-800",
  warning: "bg-warning/15 text-amber-800",
  alert: "bg-alert/10 text-red-800",
  ai: "bg-ai/10 text-ai",
};

export function Badge({ tone = "neutral", children }: { tone?: keyof typeof BADGE_TONES; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center rounded-md px-1 py-0.5 text-xs font-medium ${BADGE_TONES[tone]}`}>
      {children}
    </span>
  );
}

const BUTTON_BASE =
  "inline-flex items-center justify-center gap-1 rounded-md px-2 py-1 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-50";
export const buttonAi = `${BUTTON_BASE} bg-ai text-white hover:bg-violet-700`;
export const buttonPrimary = `${BUTTON_BASE} bg-clinical text-white hover:bg-blue-700`;
export const buttonGhost = `${BUTTON_BASE} border border-slate-300 bg-white text-ink hover:bg-slate-50`;
export const inputClass =
  "w-full rounded-md border border-slate-300 bg-white px-2 py-1 text-sm text-ink placeholder:text-slate-400 focus:border-clinical focus:outline-none focus:ring-1 focus:ring-clinical";

export function Spinner() {
  return <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-ai/30 border-t-ai" />;
}
