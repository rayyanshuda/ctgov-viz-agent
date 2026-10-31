// The sticky left navigation panel.

import { NavLink } from "react-router-dom";
import { useAsk } from "../AskContext";

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-2 py-1 text-sm ${isActive ? "bg-blue-50 font-medium text-clinical" : "text-slate-600 hover:bg-slate-50"}`;

export function Sidebar() {
  const { isPending, ready } = useAsk();

  return (
    <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r border-slate-200 bg-white/70 backdrop-blur md:flex">
      <div className="flex h-12 items-center gap-2 border-b border-slate-200 px-4">
        <span className="h-2 w-2 rounded-sm bg-ai" />
        <span className="text-sm font-semibold text-ink">CT Viz Agent</span>
      </div>

      <nav className="flex flex-col gap-1 p-2">
        {/* `end` stops "Ask" from also looking active on /charts */}
        <NavLink to="/" end className={(state) => `${linkClass(state)} flex items-center justify-between`}>
          Ask
          {/* purple pulsing dot while generating, green dot when an answer is waiting */}
          {isPending && (
            <>
              <span className="h-2 w-2 animate-pulse rounded-full bg-ai" />
              <span className="sr-only">Generating an answer</span>
            </>
          )}
          {!isPending && ready && (
            <>
              <span className="h-2 w-2 rounded-full bg-success" />
              <span className="sr-only">Answer ready</span>
            </>
          )}
        </NavLink>
        <NavLink to="/charts" className={linkClass}>
          History
        </NavLink>
      </nav>

      {/* These two are served by the backend, not by this app, so they are normal links */}
      <div className="mt-auto flex flex-col gap-1 border-t border-slate-200 p-2 text-xs">
        <a className="rounded-md px-2 py-1 text-slate-500 hover:bg-slate-50" href="/docs">
          API docs
        </a>
        <a className="rounded-md px-2 py-1 text-slate-500 hover:bg-slate-50" href="/legacy">
          Legacy demo
        </a>
      </div>
    </aside>
  );
}
