import type {
  AnalysisRow,
  Conversation,
  CreatedAnalysis,
} from "../types/analysis";

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    let message = text || "Request failed";
    try {
      const body = JSON.parse(text) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      message = text || "Request failed";
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export async function createAnalysis(
  query: string,
  conversationId: string | null,
  signal?: AbortSignal,
): Promise<CreatedAnalysis> {
  const response = await fetch("/api/analyses", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      conversation_id: conversationId,
    }),
    signal,
  });
  return parseResponse<CreatedAnalysis>(response);
}

export async function abortAnalysis(id: string): Promise<void> {
  const response = await fetch(`/api/analyses/${id}/abort`, { method: "POST" });
  await parseResponse(response);
}

export async function fetchAnalyses(): Promise<AnalysisRow[]> {
  const response = await fetch("/api/analyses");
  return parseResponse<AnalysisRow[]>(response);
}

export async function fetchConversations(): Promise<Conversation[]> {
  const response = await fetch("/api/conversations");
  return parseResponse<Conversation[]>(response);
}

export async function fetchConversation(id: string): Promise<Conversation> {
  const response = await fetch(`/api/conversations/${id}`);
  return parseResponse<Conversation>(response);
}

export async function deleteConversation(id: string): Promise<void> {
  const response = await fetch(`/api/conversations/${id}`, { method: "DELETE" });
  await parseResponse(response);
}

export async function deleteAnalysis(id: string): Promise<void> {
  const response = await fetch(`/api/analyses/${id}`, { method: "DELETE" });
  await parseResponse(response);
}

export async function clearAnalyses(): Promise<void> {
  const response = await fetch("/api/analyses", { method: "DELETE" });
  await parseResponse(response);
}

export async function fetchAnalysis(id: string): Promise<AnalysisRow> {
  const response = await fetch(`/api/analyses/${id}`);
  return parseResponse<AnalysisRow>(response);
}

export async function fetchHealth(): Promise<boolean> {
  try {
    const response = await fetch("/api/health");
    return response.ok;
  } catch {
    return false;
  }
}

export function analysisSocket(id: string): WebSocket {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return new WebSocket(
    `${protocol}://${window.location.host}/ws/analyses/${id}`,
  );
}
