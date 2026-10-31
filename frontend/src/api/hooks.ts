// React Query hooks: one per backend call. React Query handles loading flags, errors and
// caching, so components never write their own fetch + useState + useEffect.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "./client";
import type { Capabilities, RefreshResponse, SavedChartDetail, SavedChartSummary } from "./types";

export const PAGE_SIZE = 20;

// The lists of phases, statuses... don't change while the app runs, so fetch them once.
export function useCapabilities() {
  return useQuery({
    queryKey: ["capabilities"],
    queryFn: () => api.get<Capabilities>("/capabilities"),
    staleTime: Infinity,
  });
}

export function useCharts(offset: number) {
  return useQuery<SavedChartSummary[], ApiError>({
    queryKey: ["charts", offset],
    queryFn: () => api.get(`/charts?limit=${PAGE_SIZE}&offset=${offset}`),
    retry: false, // a 503 means "no database", and retrying won't fix that
  });
}

export function useChart(id: string) {
  return useQuery<SavedChartDetail, ApiError>({
    queryKey: ["chart", id],
    queryFn: () => api.get(`/charts/${id}`),
    retry: false,
  });
}

export function useRefreshChart() {
  const queryClient = useQueryClient();
  return useMutation<RefreshResponse, ApiError, string>({
    mutationFn: (id) => api.post(`/charts/${id}/refresh`),
    // The history list now has a new row
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["charts"] }),
  });
}

export function useDeleteChart() {
  const queryClient = useQueryClient();
  return useMutation<void, ApiError, string>({
    mutationFn: (id) => api.delete(`/charts/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["charts"] }),
  });
}
