import json
import os
import urllib.request
from typing import Any

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

session = boto3.Session()
credentials = session.get_credentials()
region = session.region_name or os.environ.get("AWS_REGION", "us-east-1")
NEPTUNE_ENDPOINT = os.environ["NEPTUNE_ENDPOINT"]


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    body = parse_body(event)
    start_node = body.get("start_node") or body.get("query") or ""
    depth = min(int(body.get("depth", 1)), 3)
    edge_types = body.get("edge_types") or []
    edge_filter = "WHERE r.type IN $edge_types" if edge_types else ""
    statement = f"""
    MATCH p=(n:Node {{id: $start_node}})-[r:RELATED*1..{depth}]-(m:Node)
    UNWIND relationships(p) AS rel
    WITH DISTINCT startNode(rel) AS source, endNode(rel) AS target, rel
    {edge_filter}
    RETURN source, target, rel
    LIMIT 100
    """
    result = query(statement, {"start_node": start_node, "edge_types": edge_types})
    return agent_response(event, to_cytoscape(result))


def query(statement: str, parameters: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps({"query": statement, "parameters": parameters}).encode("utf-8")
    url = f"https://{NEPTUNE_ENDPOINT}:8182/openCypher"
    request = AWSRequest(method="POST", url=url, data=body, headers={"Content-Type": "application/json"})
    SigV4Auth(credentials, "neptune-db", region).add_auth(request)
    signed = urllib.request.Request(url, data=body, headers=dict(request.headers), method="POST")
    with urllib.request.urlopen(signed, timeout=20) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def to_cytoscape(result: dict[str, Any]) -> dict[str, Any]:
    nodes = {}
    edges = {}
    for row in result.get("results", []):
        for key in ("source", "target"):
            node = row.get(key, {})
            props = node.get("~properties", node)
            node_id = props.get("id")
            if node_id:
                nodes[node_id] = {"id": node_id, "label": props.get("label", node_id), "type": props.get("type", "Node")}
        rel = row.get("rel", {})
        props = rel.get("~properties", rel)
        rel_id = props.get("id")
        if rel_id:
            edges[rel_id] = {
                "id": rel_id,
                "source": nodes.get(row.get("source", {}).get("id", ""), {}).get("id", props.get("source", "")),
                "target": nodes.get(row.get("target", {}).get("id", ""), {}).get("id", props.get("target", "")),
                "type": props.get("type", "RELATED"),
                "confidence": props.get("confidence"),
            }
    return {"nodes": list(nodes.values()), "edges": list(edges.values())}


def parse_body(event: dict[str, Any]) -> dict[str, Any]:
    request_body = event.get("requestBody", {}).get("content", {}).get("application/json", {}).get("properties", [])
    values: dict[str, Any] = {}
    for item in request_body:
        value = item.get("value")
        if item.get("type") == "array" and isinstance(value, str):
            value = json.loads(value)
        values[item["name"]] = value
    return values


def agent_response(event: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event.get("actionGroup"),
            "apiPath": event.get("apiPath"),
            "httpMethod": event.get("httpMethod"),
            "httpStatusCode": 200,
            "responseBody": {"application/json": {"body": json.dumps(payload)}},
        },
    }
