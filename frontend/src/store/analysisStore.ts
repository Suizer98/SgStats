import { create } from "zustand";

import {
  analysisSocket,
  clearAnalyses,
  createAnalysis,
  deleteAnalysis,
  fetchAnalyses,
  fetchAnalysis,
  fetchHealth,
} from "../api/analysisApi";
import { sampleQuery } from "../constants";
import type {
  AgentEvent,
  AnalysisResult,
  AnalysisRow,
} from "../types/analysis";
import { downloadFile, parseTimestamp, toCsv, toMarkdown } from "../utils/format";

type ResultTab = "chat" | "analysis";

type AnalysisState = {
  query: string;
  events: AgentEvent[];
  result: AnalysisResult | null;
  chatResult: AnalysisResult | null;
  analysisResult: AnalysisResult | null;
  chatId: string | null;
  analysisId: string | null;
  resultTab: ResultTab;
  history: AnalysisRow[];
  historyFilter: string;
  activeId: string | null;
  conversationId: string | null;
  apiOnline: boolean | null;
  busy: boolean;
  startedAt: number | null;
  error: string;
  setQuery: (query: string) => void;
  setHistoryFilter: (filter: string) => void;
  setResultTab: (tab: ResultTab) => void;
  startConversation: () => void;
  checkHealth: () => Promise<void>;
  loadHistory: () => Promise<void>;
  openHistory: (id: string) => Promise<void>;
  deleteHistory: (id: string) => Promise<void>;
  clearHistory: () => Promise<void>;
  runAnalysis: () => Promise<void>;
  exportResult: (format: "json" | "csv" | "markdown") => void;
};

type Setter = (
  partial: Partial<AnalysisState> | ((state: AnalysisState) => Partial<AnalysisState>),
) => void;
type Getter = () => AnalysisState;

let activeSocket: WebSocket | null = null;

function datasetRows(result: AnalysisResult): Record<string, unknown>[] {
  return result.datasets.flatMap((dataset) =>
    dataset.records.map((record) => ({
      source: dataset.source,
      mode: dataset.mode,
      ...record,
    })),
  );
}

// The server replays stored events on connect, so drop ids already held.
function appendEvent(events: AgentEvent[], incoming: AgentEvent): AgentEvent[] {
  if (incoming.id !== undefined && events.some((item) => item.id === incoming.id)) {
    return events;
  }
  return [...events, incoming];
}

function sameSocket(analysisId: string): boolean {
  return (
    activeSocket !== null &&
    activeSocket.readyState <= WebSocket.OPEN &&
    activeSocket.url.endsWith(`/ws/analyses/${analysisId}`)
  );
}

function storedResult(result: AnalysisResult, id: string): Partial<AnalysisState> {
  if (result.kind === "chat") {
    return { result, chatResult: result, chatId: id, resultTab: "chat" };
  }
  return { result, analysisResult: result, analysisId: id, resultTab: "analysis" };
}

function applyLoaded(row: AnalysisRow, set: Setter, get: Getter): void {
  const running = row.status === "running";
  const current = get();
  set({
    query: row.query,
    events:
      row.id === current.activeId && row.events.length < current.events.length
        ? current.events
        : row.events,
    ...(row.result ? storedResult(row.result, row.id) : {}),
    activeId: row.id,
    conversationId: row.conversation_id,
    busy: running,
    startedAt: running
      ? parseTimestamp(row.created_at)?.getTime() ?? current.startedAt
      : null,
    error: row.status === "failed" ? row.error || "Analysis failed." : "",
  });
  if (running) attachSocket(row.id, set, get);
  else activeSocket?.close();
}

function attachSocket(analysisId: string, set: Setter, get: Getter): void {
  if (sameSocket(analysisId)) return;
  activeSocket?.close();
  const socket = analysisSocket(analysisId);
  activeSocket = socket;

  socket.onmessage = (message) => {
    const payload = JSON.parse(message.data) as AgentEvent;

    if (payload.step === "done" && payload.result) {
      set({ ...storedResult(payload.result, analysisId), busy: false });
      void get().loadHistory();
      socket.close();
      return;
    }

    if (payload.step === "error") {
      set({ error: payload.content || "Analysis failed.", busy: false });
      void get().loadHistory();
      socket.close();
      return;
    }

    set((state) => ({ events: appendEvent(state.events, payload) }));
  };

  socket.onerror = () => {
    set({ error: "Live updates disconnected. The analysis keeps running on the server." });
  };

  socket.onclose = () => {
    if (activeSocket === socket) {
      activeSocket = null;
    }
  };
}

export const useAnalysisStore = create<AnalysisState>((set, get) => ({
  query: sampleQuery,
  events: [],
  result: null,
  chatResult: null,
  analysisResult: null,
  chatId: null,
  analysisId: null,
  resultTab: "chat",
  history: [],
  historyFilter: "",
  activeId: null,
  conversationId: null,
  apiOnline: null,
  busy: false,
  startedAt: null,
  error: "",

  setQuery: (query) => set({ query }),

  setHistoryFilter: (historyFilter) => set({ historyFilter }),

  setResultTab: (resultTab) => set({ resultTab }),

  startConversation: () => {
    activeSocket?.close();
    set({
      conversationId: null,
      activeId: null,
      events: [],
      result: null,
      chatResult: null,
      analysisResult: null,
      chatId: null,
      analysisId: null,
      resultTab: "chat",
      busy: false,
      error: "",
    });
  },

  checkHealth: async () => {
    set({ apiOnline: await fetchHealth() });
  },

  loadHistory: async () => {
    try {
      set({ history: await fetchAnalyses() });
    } catch {
      set({ error: "Could not load analysis history." });
    }
  },

  openHistory: async (id) => {
    try {
      const row = await fetchAnalysis(id);
      applyLoaded(row, set, get);
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : "Could not load analysis.",
      });
    }
  },

  deleteHistory: async (id) => {
    try {
      await deleteAnalysis(id);
      const current = get();
      const clearedChat = current.chatId === id;
      const clearedAnalysis = current.analysisId === id;
      const chatResult = clearedChat ? null : current.chatResult;
      const analysisResult = clearedAnalysis ? null : current.analysisResult;
      if (current.activeId === id) {
        activeSocket?.close();
        set({
          activeId: null,
          conversationId: null,
          events: [],
          busy: false,
          error: "",
          chatResult,
          analysisResult,
          chatId: clearedChat ? null : current.chatId,
          analysisId: clearedAnalysis ? null : current.analysisId,
          result: analysisResult ?? chatResult,
          resultTab: analysisResult ? "analysis" : "chat",
        });
      } else if (clearedChat || clearedAnalysis) {
        set({
          chatResult,
          analysisResult,
          chatId: clearedChat ? null : current.chatId,
          analysisId: clearedAnalysis ? null : current.analysisId,
          result: current.activeId ? current.result : analysisResult ?? chatResult,
        });
      }
      set({ history: get().history.filter((row) => row.id !== id) });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : "Could not delete that run.",
      });
    }
  },

  clearHistory: async () => {
    try {
      await clearAnalyses();
      const history = await fetchAnalyses();
      const activeId = get().activeId;
      if (activeId && !history.some((row) => row.id === activeId)) {
        activeSocket?.close();
        set({
          history,
          activeId: null,
          conversationId: null,
          events: [],
          result: null,
          chatResult: null,
          analysisResult: null,
          chatId: null,
          analysisId: null,
          resultTab: "chat",
          busy: false,
          error: "",
        });
        return;
      }
      set({ history });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : "Could not clear history.",
      });
    }
  },

  runAnalysis: async () => {
    if (get().busy) return;
    const query = get().query.trim();
    if (!query) {
      set({ error: "Enter a policy question." });
      return;
    }

    activeSocket?.close();
    set({
      busy: true,
      error: "",
      events: [],
      startedAt: Date.now(),
    });

    try {
      const created = await createAnalysis(query, get().conversationId);
      set({
        activeId: created.id,
        conversationId: created.conversation_id,
      });
      attachSocket(created.id, set, get);
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : "Request failed.",
        busy: false,
      });
    }
  },

  exportResult: (format) => {
    const result = get().analysisResult;
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
