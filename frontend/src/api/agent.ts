export type GraphNode = {
  id: string;
  label?: string;
  type?: string;
};

export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  type?: string;
  confidence?: number;
};

export type AgentResponse = {
  session_id: string;
  summary: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  citations: unknown[];
};

const apiUrl = import.meta.env.VITE_API_URL;

export async function askAgent(query: string, sessionId?: string): Promise<AgentResponse> {
  if (!apiUrl) {
    throw new Error("VITE_API_URL is not configured");
  }
  const response = await fetch(`${apiUrl.replace(/\/$/, "")}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, session_id: sessionId }),
  });
  if (!response.ok) {
    throw new Error(`Agent request failed: ${response.status}`);
  }
  return response.json();
}
