import { GraphNode } from "../api/agent";

type Props = {
  selectedNode?: GraphNode;
  summary: string;
  citations: unknown[];
};

export function DetailPanel({ selectedNode, summary, citations }: Props) {
  return (
    <aside className="detail-panel">
      <h2>{selectedNode?.label ?? "Feature Details"}</h2>
      {selectedNode && (
        <dl>
          <dt>ID</dt>
          <dd>{selectedNode.id}</dd>
          <dt>Type</dt>
          <dd>{selectedNode.type ?? "Node"}</dd>
        </dl>
      )}
      <h3>Answer</h3>
      <p>{summary || "Search for a feature to see 3GPP details and related whitepaper context."}</p>
      <h3>Citations</h3>
      {citations.length === 0 ? (
        <p>No citations returned yet.</p>
      ) : (
        <pre>{JSON.stringify(citations, null, 2)}</pre>
      )}
    </aside>
  );
}
