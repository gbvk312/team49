import json
import os
import re
import uuid
from typing import Any

import boto3

agent_runtime = boto3.client("bedrock-agent-runtime")

AGENT_ID = os.environ["AGENT_ID"]
AGENT_ALIAS_ID = os.environ["AGENT_ALIAS_ID"]
CORS_ORIGIN = os.environ.get("CORS_ORIGIN", "*")


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return response(204, {})

    body = json.loads(event.get("body") or "{}")
    question = body.get("query") or body.get("message") or ""
    session_id = body.get("session_id") or str(uuid.uuid4())
    if not question:
        return response(400, {"error": "query is required"})

    completion = agent_runtime.invoke_agent(
        agentId=AGENT_ID,
        agentAliasId=AGENT_ALIAS_ID,
        sessionId=session_id,
        inputText=question,
        enableTrace=False,
    )["completion"]

    text = ""
    for event_chunk in completion:
        if "chunk" in event_chunk:
            text += event_chunk["chunk"]["bytes"].decode("utf-8")

    return response(200, {"session_id": session_id, **shape_agent_text(text)})


def shape_agent_text(text: str) -> dict[str, Any]:
    graph = extract_json_block(text)
    return {
        "summary": text,
        "nodes": graph.get("nodes", []) if graph else [],
        "edges": graph.get("edges", []) if graph else [],
        "citations": graph.get("citations", []) if graph else [],
    }


def extract_json_block(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{[\s\S]*\"nodes\"[\s\S]*\"edges\"[\s\S]*\}", text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "isBase64Encoded": False,
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": CORS_ORIGIN,
            "Access-Control-Allow-Methods": "OPTIONS,POST",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
        },
        "body": json.dumps(body),
    }
