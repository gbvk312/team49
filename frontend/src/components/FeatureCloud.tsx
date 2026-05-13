import cytoscape, { Core } from "cytoscape";
import { useEffect, useRef } from "react";
import { GraphEdge, GraphNode } from "../api/agent";

type Props = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  onNodeSelect: (node: GraphNode) => void;
};

export function FeatureCloud({ nodes, edges, onNodeSelect }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const cyRef = useRef<Core | null>(null);

  useEffect(() => {
    if (!containerRef.current || cyRef.current) {
      return;
    }
    cyRef.current = cytoscape({
      container: containerRef.current,
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            "background-color": "#2563eb",
            color: "#0f172a",
            "font-size": "11px",
            "text-valign": "bottom",
            "text-halign": "center",
          },
        },
        { selector: 'node[type = "Feature"]', style: { "background-color": "#16a34a" } },
        { selector: 'node[type = "Whitepaper"]', style: { "background-color": "#f97316" } },
        { selector: 'node[type = "Spec"]', style: { "background-color": "#7c3aed" } },
        {
          selector: "edge",
          style: {
            width: 2,
            "line-color": "#94a3b8",
            "target-arrow-color": "#94a3b8",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            label: "data(type)",
            "font-size": "9px",
          },
        },
      ],
    });
    cyRef.current.on("tap", "node", (event) => {
      const data = event.target.data() as GraphNode;
      onNodeSelect(data);
    });
  }, [onNodeSelect]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) {
      return;
    }
    cy.elements().remove();
    cy.add(nodes.map((node) => ({ group: "nodes", data: { label: node.label ?? node.id, type: node.type, ...node } })));
    cy.add(edges.map((edge) => ({ group: "edges", data: edge })));
    cy.layout({ name: "cose", animate: true, fit: true, padding: 40 }).run();
  }, [nodes, edges]);

  return <div className="feature-cloud" ref={containerRef} />;
}
