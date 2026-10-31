// The page frame (left nav, plus a question box docked at the bottom of History and saved
// charts) and the three routes.

import { Route, Routes, useLocation } from "react-router-dom";
import { AnimatedBackground } from "./components/AnimatedBackground";
import { AskDock } from "./components/AskDock";
import { Sidebar } from "./components/Sidebar";
import { AskPage } from "./pages/AskPage";
import { ChartPage } from "./pages/ChartPage";
import { HistoryPage } from "./pages/HistoryPage";

export default function App() {
  const onAskPage = useLocation().pathname === "/";

  return (
    // isolate makes this its own stacking layer, so the background (z -10) sits behind the
    // content but still in front of the page colour
    <div className="relative isolate flex min-h-screen">
      <AnimatedBackground />
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        {/* pb-16 leaves room for the question box docked at the bottom (every page except Ask) */}
        <main className={onAskPage ? "p-4" : "p-4 pb-16"}>
          <Routes>
            <Route path="/" element={<AskPage />} />
            <Route path="/charts" element={<HistoryPage />} />
            <Route path="/c/:id" element={<ChartPage />} />
            <Route path="*" element={<p className="text-sm text-slate-600">Page not found.</p>} />
          </Routes>
        </main>
      </div>
      <AskDock />
    </div>
  );
}
