import { create } from "zustand";

import {
  abortAnalysis,
  analysisSocket,
  clearAnalyses,
  createAnalysis,
  deleteConversation,
  fetchAnalysis,
  fetchConversation,
  fetchConversations,
  fetchHealth,
} from "../api/analysisApi";
import { sampleQuery } from "../constants";
import type {
  AgentEvent,
  AnalysisResult,
  AnalysisRow,
  Conversation,
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
  history: Conversation[];
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
  abortRun: () => Promise<void>;
  exportResult: (format: "json" | "csv" | "markdown") => void;
};

type Setter = (
  partial: Partial<AnalysisState> | ((state: AnalysisState) => Partial<AnalysisState>),
) => void;
type Getter = () => AnalysisState;

let activeSocket: WebSocket | null = null;
let createRequest: AbortController | null = null;

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

function threadResults(analyses: AnalysisRow[]): {
  chatResult: AnalysisResult | null;
  chatId: string | null;
  analysisResult: AnalysisResult | null;
  analysisId: string | null;
} {
  let chatResult: AnalysisResult | null = null;
  let chatId: string | null = null;
  let analysisResult: AnalysisResult | null = null;
  let analysisId: string | null = null;
  for (const row of analyses) {
    if (!row.result) continue;
    if (row.result.kind === "chat") {
      chatResult = row.result;
      chatId = row.id;
    } else {
      analysisResult = row.result;
      analysisId = row.id;
    }
  }
  return { chatResult, chatId, analysisResult, analysisId };
}

function applyThread(conversation: Conversation, focus: AnalysisRow, set: Setter, get: Getter): void {
  const analyses = conversation.analyses.map((row) => (row.id === focus.id ? focus : row));
  const picked = threadResults(analyses);
  const completed = [...analyses].reverse().find((row) => row.result);
  const shown = focus.result ? focus : completed;
  const resultTab = shown?.result?.kind === "chat" ? "chat" : shown?.result ? "analysis" : "chat";
  const running = focus.status === "running";
  const current = get();
  set({
    query: focus.query,
    events:
      focus.id === current.activeId && focus.events.length < current.events.length
        ? current.events
        : focus.events,
    ...picked,
    result: shown?.result ?? null,
    resultTab,
    activeId: focus.id,
    conversationId: conversation.id,
    busy: running,
    startedAt: running
      ? parseTimestamp(focus.created_at)?.getTime() ?? current.startedAt
      : null,
    error: focus.status === "failed" ? focus.error || "Analysis failed." : "",
  });
  if (running) attachSocket(focus.id, set, get);
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
      set({ history: await fetchConversations() });
    } catch {
      set({ error: "Could not load analysis history." });
    }
  },

  openHistory: async (id) => {
    try {
      const conversation = await fetchConversation(id);
      const analyses = conversation.analyses;
      const running = [...analyses].reverse().find((row) => row.status === "running");
      const latest = analyses[analyses.length - 1];
      const focusId = (running ?? latest)?.id;
      if (!focusId) {
        set({
          conversationId: conversation.id,
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
        return;
      }
      const focus = await fetchAnalysis(focusId);
      applyThread(conversation, focus, set, get);
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : "Could not load analysis.",
      });
    }
  },

  deleteHistory: async (id) => {
    try {
      await deleteConversation(id);
      if (get().conversationId === id) {
        activeSocket?.close();
        set({
          activeId: null,
          conversationId: null,
          events: [],
          busy: false,
          error: "",
          result: null,
          chatResult: null,
          analysisResult: null,
          chatId: null,
          analysisId: null,
          resultTab: "chat",
        });
      }
      set({ history: get().history.filter((row) => row.id !== id) });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : "Could not delete that thread.",
      });
    }
  },

  clearHistory: async () => {
    try {
      await clearAnalyses();
      const history = await fetchConversations();
      const conversationId = get().conversationId;
      if (conversationId && !history.some((row) => row.id === conversationId)) {
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
    createRequest?.abort();
    const request = new AbortController();
    createRequest = request;
    set({
      busy: true,
      activeId: null,
      error: "",
      events: [],
      startedAt: Date.now(),
    });

    try {
      const created = await createAnalysis(query, get().conversationId, request.signal);
      set({
        activeId: created.id,
        conversationId: created.conversation_id,
      });
      attachSocket(created.id, set, get);
      void get().loadHistory();
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        set({ busy: false, error: "Stopped." });
        return;
      }
      set({
        error: error instanceof Error ? error.message : "Request failed.",
        busy: false,
      });
    } finally {
      if (createRequest === request) createRequest = null;
    }
  },

  abortRun: async () => {
    if (!get().busy) return;
    createRequest?.abort();
    const id = get().activeId;
    if (!id) {
      set({ busy: false, error: "Stopped." });
      return;
    }
    try {
      await abortAnalysis(id);
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : "Could not stop that run.",
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
