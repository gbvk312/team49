import json
import os
import urllib.request
from typing import Any

import boto3
from botocore.awsrequest import AWSRequest
from botocore.auth import SigV4Auth

session = boto3.Session()
credentials = session.get_credentials()
region = session.region_name or os.environ.get("AWS_REGION", "us-east-1")

NEPTUNE_ENDPOINT = os.environ["NEPTUNE_ENDPOINT"]


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    nodes = event.get("nodes", [])
    edges = event.get("edges", [])
    for node in nodes:
        query(
            "MERGE (n:Node {id: $id}) SET n.label = $label, n.type = $type",
            {"id": node["id"], "label": node.get("label", node["id"]), "type": node.get("type", "Node")},
        )
    for edge in edges:
        query(
            """
            MATCH (s:Node {id: $source})
            MATCH (t:Node {id: $target})
            MERGE (s)-[r:RELATED {id: $id}]->(t)
            SET r.type = $type, r.confidence = $confidence, r.chunk_id = $chunk_id
            """,
            {
                "id": edge["id"],
                "source": edge["source"],
                "target": edge["target"],
                "type": edge["type"],
                "confidence": edge.get("confidence", 1.0),
                "chunk_id": edge.get("chunk_id", ""),
            },
        )
    return {**event, "graph_written": {"nodes": len(nodes), "edges": len(edges)}}


def query(statement: str, parameters: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps({"query": statement, "parameters": parameters}).encode("utf-8")
    url = f"https://{NEPTUNE_ENDPOINT}:8182/openCypher"
    request = AWSRequest(method="POST", url=url, data=body, headers={"Content-Type": "application/json"})
    SigV4Auth(credentials, "neptune-db", region).add_auth(request)
    signed = urllib.request.Request(url, data=body, headers=dict(request.headers), method="POST")
    with urllib.request.urlopen(signed, timeout=20) as response:
        return json.loads(response.read().decode("utf-8") or "{}")
