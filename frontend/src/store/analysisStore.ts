import { create } from "zustand";

import type { AnalysisResult } from "../types/analysis";
import { downloadFile, toCsv, toMarkdown } from "../utils/format";

type AnalysisState = {
  analysisResult: AnalysisResult | null;
  analysisId: string | null;
  setAnalysisResult: (result: AnalysisResult, id: string) => void;
  resetAnalysis: () => void;
  exportResult: (format: "json" | "csv" | "markdown", source?: AnalysisResult) => void;
};

function datasetRows(result: AnalysisResult): Record<string, unknown>[] {
  return result.datasets.flatMap((dataset) =>
    dataset.records.map((record) => ({
      source: dataset.source,
      mode: dataset.mode,
      ...record,
    })),
  );
}

// Holds the "Analysis" side of a result thread: the structured report,
// charts/datasets and export actions. The conversational side (chat
// messages, history, websocket plumbing) lives in chatStore.ts, which
// calls setAnalysisResult/resetAnalysis whenever a new analysis result
// arrives for the active thread.
export const useAnalysisStore = create<AnalysisState>((set, get) => ({
  analysisResult: null,
  analysisId: null,

  setAnalysisResult: (result, id) => set({ analysisResult: result, analysisId: id }),

  resetAnalysis: () => set({ analysisResult: null, analysisId: null }),

  exportResult: (format, source) => {
    const result = source ?? get().analysisResult;
    if (!result) return;

    if (format === "csv") {
      downloadFile(toCsv(datasetRows(result)), "sgstats-data.csv", "text/csv");
      return;
    }

    if (format === "markdown") {
      downloadFile(toMarkdown(result), "sgstats-briefing.md", "text/markdown");
      return;
    }

    downloadFile(
      JSON.stringify(result, null, 2),
      "sgstats-report.json",
      "application/json",
    );
  },
}));
