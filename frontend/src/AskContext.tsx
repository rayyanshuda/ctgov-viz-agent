// Holds the "ask a question" state in one place, so the search box in the top bar, the
// filter fields on the Ask page and the result all stay in sync, and the last result is
// still there if you visit History and come back.

import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "./api/client";
import type { VisualizeResponse } from "./api/types";
import { buildRequest, EMPTY_FILTERS, type Filters } from "./ask";

interface AskState {
  query: string;
  setQuery: (q: string) => void;
  filters: Filters;
  setFilters: (f: Filters) => void;
  // Send the question to the agent. Pass a question/filters to run those instead of
  // what is currently typed (used by example chips and deep links).
  submit: (question?: string, filters?: Filters) => void;
  needsQuestion: boolean; // true when filters were set but no question was typed
  idle: boolean; // nothing asked yet: the Ask page shows its centred welcome view
  data: VisualizeResponse | undefined;
  error: ApiError | null;
  isPending: boolean;
  // true when an answer has arrived that the user has not looked at yet (they were on
  // another page when it finished). Used for the "Answer ready" hints.
  ready: boolean;
  markSeen: (answer: VisualizeResponse) => void;
}

const AskContext = createContext<AskState | null>(null);

export function AskProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [needsQuestion, setNeedsQuestion] = useState(false);
  const [seen, setSeen] = useState<VisualizeResponse | undefined>();

  const mutation = useMutation<VisualizeResponse, ApiError, ReturnType<typeof buildRequest>>({
    mutationFn: (body) => api.post("/visualize", body),
    // A saved chart was just created, so the History list is out of date
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["charts"] }),
  });

  const submit = useCallback(
    (question?: string, overrideFilters?: Filters) => {
      if (mutation.isPending) return;
      const q = (question ?? query).trim();
      const f = overrideFilters ?? filters;
      if (question !== undefined) setQuery(question);
      if (overrideFilters !== undefined) setFilters(overrideFilters);

      if (q.length < 3) {
        setNeedsQuestion(true);
        return;
      }
      setNeedsQuestion(false);
      mutation.mutate(buildRequest(q, f));
    },
    [mutation, query, filters],
  );

  return (
    <AskContext.Provider
      value={{
        query,
        setQuery,
        filters,
        setFilters,
        submit,
        needsQuestion,
        idle: !mutation.data && !mutation.isPending && !mutation.error && !needsQuestion,
        data: mutation.data,
        error: mutation.error,
        isPending: mutation.isPending,
        ready: !!mutation.data && seen !== mutation.data,
        markSeen: setSeen,
      }}
    >
      {children}
    </AskContext.Provider>
  );
}

export function useAsk(): AskState {
  const ctx = useContext(AskContext);
  if (!ctx) throw new Error("useAsk must be used inside <AskProvider>");
  return ctx;
}
