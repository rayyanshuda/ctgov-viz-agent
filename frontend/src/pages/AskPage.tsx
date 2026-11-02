// The main page. Before anything is asked it is a centred welcome view with the question
// box in the middle; after that the filters and the question box sit together in one card at
// the top (InputPanel), with the agent's answer below it.

import { useEffect, useRef } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useAsk } from "../AskContext";
import { EXAMPLES, filtersFromParams, suggestedQuestions } from "../ask";
import { AskBox } from "../components/AskBox";
import { Badge, Card, Spinner, buttonGhost } from "../components/ui";
import { ChartResult } from "../components/ChartResult";
import { CopyLinkButton } from "../components/CopyLinkButton";
import { ErrorBanner } from "../components/ErrorBanner";
import { FilterForm } from "../components/FilterForm";
import { InputPanel } from "../components/InputPanel";

// A row of clickable questions
function Chips({ questions, onPick }: { questions: string[]; onPick: (q: string) => void }) {
  return (
    <div className="flex flex-wrap gap-2">
      {questions.map((q) => (
        <button key={q} className={buttonGhost} title={q} onClick={() => onPick(q)}>
          {q.length > 64 ? q.slice(0, 62) + "…" : q}
        </button>
      ))}
    </div>
  );
}

export function AskPage() {
  const { data, error, isPending, needsQuestion, idle, filters, submit, markSeen } = useAsk();
  const [params] = useSearchParams();

  // Links like /?q=...&drug=... run the question once when the page opens.
  // The ref stops React's dev-mode double-run from asking (and paying for) it twice.
  const ranFromLink = useRef(false);
  useEffect(() => {
    const q = params.get("q");
    if (!q || ranFromLink.current) return;
    ranFromLink.current = true;
    submit(q, filtersFromParams(params));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Being on this page means any finished answer is now seen, so the "Answer ready" hints clear
  useEffect(() => {
    if (data) markSeen(data);
  }, [data, markSeen]);

  // Nothing asked yet: a centred welcome view. The min height is the screen minus the 2rem of
  // page padding, so the content sits in the middle of the screen.
  if (idle) {
    return (
      <div className="mx-auto flex min-h-[calc(100vh-2rem)] max-w-4xl flex-col justify-center gap-4">
        <div>
          <h1 className="text-3xl font-semibold text-ink">Ask about clinical trials</h1>
          <p className="mt-1 text-sm text-slate-600">
            Clinical trials can be confusing and complex. 
            Ask questions and this agent will handle the analysis, 
            fetch data from ClinicalTrials.gov, and map it into 
            interactive visualizations with citations. Give it a try!
          </p>
        </div>
        <AskBox large />
        <FilterForm />
        <Chips questions={EXAMPLES} onPick={(q) => submit(q)} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <InputPanel />

      {needsQuestion && (
        <Card title="A question is required">
          <p className="mb-2 text-sm text-slate-600">
            The filters decide <em>which</em> trials are retrieved; the question decides <em>what to show</em> about
            them. Type one in the question box above, or pick one of these sample questions to see how the agent works:
          </p>
          <Chips questions={suggestedQuestions(filters)} onPick={(q) => submit(q)} />
        </Card>
      )}

      {isPending && (
        <Card>
          <div className="flex items-center gap-2 text-sm text-ai">
            <Spinner />
            Planning the analysis and retrieving trials from ClinicalTrials.gov…
          </div>
        </Card>
      )}

      {error && <ErrorBanner error={error} />}

      {data && !isPending && (
        <ChartResult
          response={data}
          actions={
            data.chart_id ? (
              <div className="flex items-center gap-2 text-xs text-slate-600">
                <Badge tone="success">Saved</Badge>
                <Link className="text-clinical hover:underline" to={`/c/${data.chart_id}`}>
                  Open share page
                </Link>
                <CopyLinkButton chartId={data.chart_id} />
              </div>
            ) : null
          }
        />
      )}
    </div>
  );
}
