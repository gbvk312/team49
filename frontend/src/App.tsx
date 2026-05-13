import { FormEvent, useCallback, useState } from "react";
import { AgentResponse, askAgent, GraphEdge, GraphNode } from "./api/agent";
import { DetailPanel } from "./components/DetailPanel";
import { FeatureCloud } from "./components/FeatureCloud";

export function App() {
  const [query, setQuery] = useState("Measurement Reporting in TS 38.331 Rel-18");
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [summary, setSummary] = useState("");
  const [citations, setCitations] = useState<unknown[]>([]);
  const [selectedNode, setSelectedNode] = useState<GraphNode | undefined>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | undefined>();

  const mergeGraph = (response: AgentResponse) => {
    setNodes((current) => dedupe([...current, ...response.nodes]));
    setEdges((current) => dedupe([...current, ...response.edges]));
    setSummary(response.summary);
    setCitations(response.citations ?? []);
    setSessionId(response.session_id);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError(undefined);
    try {
      mergeGraph(await askAgent(query, sessionId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  };

  const expandNode = useCallback(
    async (node: GraphNode) => {
      setSelectedNode(node);
      setLoading(true);
      try {
        mergeGraph(await askAgent(`Expand graph around node ${node.id} with depth 1`, sessionId));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unknown error");
      } finally {
        setLoading(false);
      }
    },
    [sessionId],
  );

  return (
    <main>
      <section className="workspace">
        <header>
          <h1>3GPP Feature Cloud</h1>
          <form onSubmit={submit}>
            <input value={query} onChange={(event) => setQuery(event.target.value)} />
            <button disabled={loading}>{loading ? "Searching..." : "Search"}</button>
          </form>
          {error && <p className="error">{error}</p>}
        </header>
        <FeatureCloud nodes={nodes} edges={edges} onNodeSelect={expandNode} />
      </section>
      <DetailPanel selectedNode={selectedNode} summary={summary} citations={citations} />
    </main>
  );
}

function dedupe<T extends { id: string }>(items: T[]): T[] {
  return Object.values(Object.fromEntries(items.map((item) => [item.id, item])));
}
