// The question input and Ask button. Three pieces, so it can be used in different places:
//   useAskSubmit - what happens when the form is submitted
//   AskFields    - just the input + button (put it inside any <form>)
//   AskBox       - AskFields wrapped in its own form (the welcome view and the bottom bar)

import { useLocation, useNavigate } from "react-router-dom";
import { useAsk } from "../AskContext";
import { EMPTY_FILTERS } from "../ask";
import { buttonAi, inputClass, Spinner } from "./ui";

export function useAskSubmit() {
  const { filters, submit } = useAsk();
  const navigate = useNavigate();
  const onAskPage = useLocation().pathname === "/";

  return (e: React.FormEvent) => {
    e.preventDefault();
    if (onAskPage) {
      submit(undefined, filters);
    } else {
      // Filters from the Ask page are out of sight here, so don't apply them silently
      navigate("/");
      submit(undefined, EMPTY_FILTERS);
    }
  };
}

export function AskFields({ large = false }: { large?: boolean }) {
  const { query, setQuery, isPending } = useAsk();

  return (
    <div className="flex gap-2">
      <input
        // the trailing "!" makes the large size win over the default input size
        className={`${inputClass} ${large ? "py-2! text-base!" : ""}`}
        aria-label="Ask a question about clinical trials"
        placeholder="Ask about clinical trials, e.g. How are melanoma trials distributed across phases?"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        autoFocus={large}
      />
      <button type="submit" className={`${buttonAi} shrink-0 ${large ? "px-4! py-2! text-sm!" : ""}`} disabled={isPending}>
        {isPending && <Spinner />}
        Ask
      </button>
    </div>
  );
}

export function AskBox({ large = false }: { large?: boolean }) {
  return (
    <form onSubmit={useAskSubmit()} role="search">
      <AskFields large={large} />
    </form>
  );
}
