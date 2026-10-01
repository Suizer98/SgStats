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
import { useAnalysisStore } from "./analysisStore";
import type {
  AgentEvent,
  AnalysisResult,
  AnalysisRow,
  Conversation,
} from "../types/analysis";
import { parseTimestamp } from "../utils/format";

type ChatState = {
  query: string;
  events: AgentEvent[];
  result: AnalysisResult | null;
  chatResult: AnalysisResult | null;
  chatMessages: AnalysisResult[];
  chatId: string | null;
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
  startConversation: () => void;
  checkHealth: () => Promise<void>;
  loadHistory: () => Promise<void>;
  openHistory: (id: string) => Promise<void>;
  deleteHistory: (id: string) => Promise<void>;
  clearHistory: () => Promise<void>;
  runAnalysis: () => Promise<void>;
  abortRun: () => Promise<void>;
};

type Setter = (
  partial: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>),
) => void;
type Getter = () => ChatState;

let activeSocket: WebSocket | null = null;
let createRequest: AbortController | null = null;

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

function toChatResult(result: AnalysisResult): AnalysisResult {
  if (result.kind === "chat") return result;
  return {
    ...result,
    kind: "chat",
    report: {
      ...result.report,
      title: "Conversation",
      briefing: result.report.chat_message ?? result.report.briefing,
      insights: [],
      citations: [],
    },
    plan: [],
    datasets: [],
    summary: { metrics: [], charts: [], correlations: [] },
  };
}

// Clears both the chat-side and analysis-side state for a fresh/empty thread.
function emptyThreadState(): Partial<ChatState> {
  useAnalysisStore.getState().resetAnalysis();
  return {
    activeId: null,
    events: [],
    result: null,
    chatResult: null,
    chatMessages: [],
    chatId: null,
  };
}

type Updater = (state: ChatState) => Partial<ChatState>;

function storedResult(result: AnalysisResult, id: string): Updater {
  if (result.kind === "chat") {
    return (state: ChatState) => {
      const exists = state.chatMessages.some((msg) => msg.query === result.query);
      return {
        result,
        chatResult: result,
        chatId: id,
        chatMessages: exists ? state.chatMessages : [...state.chatMessages, result],
      };
    };
  }
  // For analysis results, also add the chat version to chatMessages and
  // push the structured report into the analysis store.
  const chatVersion = toChatResult(result);
  useAnalysisStore.getState().setAnalysisResult(result, id);
  return (state: ChatState) => {
    const exists = state.chatMessages.some((msg) => msg.query === result.query);
    return {
      result,
      chatResult: chatVersion,
      chatId: id,
      chatMessages: exists ? state.chatMessages : [...state.chatMessages, chatVersion],
    };
  };
}

function threadResults(analyses: AnalysisRow[]): {
  chatResult: AnalysisResult | null;
  chatMessages: AnalysisResult[];
  chatId: string | null;
  analysisResult: AnalysisResult | null;
  analysisId: string | null;
} {
  let chatResult: AnalysisResult | null = null;
  let chatId: string | null = null;
  const chatMessages: AnalysisResult[] = [];
  const seenQueries = new Set<string>();
  let analysisResult: AnalysisResult | null = null;
  let analysisId: string | null = null;
  for (const row of analyses) {
    if (!row.result) continue;
    if (row.result.kind === "chat") {
      chatResult = row.result;
      chatId = row.id;
      if (!seenQueries.has(row.result.query)) {
        chatMessages.push(row.result);
        seenQueries.add(row.result.query);
      }
    } else {
      analysisResult = row.result;
      analysisId = row.id;
      chatResult = toChatResult(row.result);
      chatId = row.id;
      const chatVersion = toChatResult(row.result);
      if (!seenQueries.has(row.result.query)) {
        chatMessages.push(chatVersion);
        seenQueries.add(row.result.query);
      }
    }
  }
  return { chatResult, chatId, analysisResult, analysisId, chatMessages };
}

function applyThread(conversation: Conversation, focus: AnalysisRow, set: Setter, get: Getter): void {
  const analyses = conversation.analyses.map((row) => (row.id === focus.id ? focus : row));
  const picked = threadResults(analyses);
  const completed = [...analyses].reverse().find((row) => row.result);
  const shown = focus.result ? focus : completed;
  const resultTab = picked.chatResult ? "chat" : shown?.result ? "analysis" : "chat";
  const running = focus.status === "running";
  const current = get();

  if (picked.analysisResult && picked.analysisId) {
    useAnalysisStore.getState().setAnalysisResult(picked.analysisResult, picked.analysisId);
  } else {
    useAnalysisStore.getState().resetAnalysis();
  }
  useAnalysisStore.getState().setResultTab(resultTab);

  set({
    query: focus.query,
    events:
      focus.id === current.activeId && focus.events.length < current.events.length
        ? current.events
        : focus.events,
    chatResult: picked.chatResult,
    chatMessages: picked.chatMessages,
    chatId: picked.chatId,
    result: shown?.result ?? null,
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
      const resultUpdate = storedResult(payload.result, analysisId);
      set((state) => ({
        ...resultUpdate(state),
        busy: false,
      }));
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

export const useChatStore = create<ChatState>((set, get) => ({
  query: sampleQuery,
  events: [],
  result: null,
  chatResult: null,
  chatMessages: [],
  chatId: null,
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

  startConversation: () => {
    activeSocket?.close();
    set({
      conversationId: null,
      busy: false,
      error: "",
      ...emptyThreadState(),
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
          busy: false,
          error: "",
          ...emptyThreadState(),
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
          conversationId: null,
          ...emptyThreadState(),
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
          conversationId: null,
          busy: false,
          error: "",
          ...emptyThreadState(),
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
}));
