// The question box fixed to the bottom of the screen on History and saved-chart pages, so you
// can ask from anywhere. It is not used on the Ask page, which has its own input card.
//
// It also shows a one-line status, so it is clear that an answer is being generated (or is
// ready) even though the progress card lives on the Ask page.

import { Link, useLocation } from "react-router-dom";
import { useAsk } from "../AskContext";
import { AskBox } from "./AskBox";
import { Spinner } from "./ui";

export function AskDock() {
  const { isPending, ready } = useAsk();
  if (useLocation().pathname === "/") return null;

  // md:left-56 leaves room for the sidebar, which is hidden on small screens
  return (
    <div className="fixed bottom-0 left-0 right-0 z-20 border-t border-slate-200 bg-white/80 p-2 backdrop-blur md:left-56">
      <div className="mx-auto flex max-w-3xl flex-col gap-1">
        {isPending && (
          <Link to="/" className="flex items-center gap-2 text-xs font-medium text-ai hover:underline">
            <Spinner />
            Generating your answer… View progress
          </Link>
        )}
        {ready && (
          <Link to="/" className="text-xs font-medium text-emerald-700 hover:underline">
            ✓ Your answer is ready. View
          </Link>
        )}
        <AskBox />
      </div>
    </div>
  );
}
