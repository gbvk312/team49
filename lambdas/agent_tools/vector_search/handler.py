import json
import os
from typing import Any

import boto3

runtime = boto3.client("bedrock-agent-runtime")
KNOWLEDGE_BASE_ID = os.environ["KNOWLEDGE_BASE_ID"]


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    body = parse_body(event)
    query = body.get("query", "")
    top_k = int(body.get("top_k", 5))
    filters = body.get("filters") or {}
    retrieval_config: dict[str, Any] = {"vectorSearchConfiguration": {"numberOfResults": top_k}}
    if filters:
        retrieval_config["vectorSearchConfiguration"]["filter"] = equals_filter(filters)

    response = runtime.retrieve(
        knowledgeBaseId=KNOWLEDGE_BASE_ID,
        retrievalQuery={"text": query},
        retrievalConfiguration=retrieval_config,
    )
    results = [
        {
            "content": item.get("content", {}).get("text", ""),
            "score": item.get("score"),
            "metadata": item.get("metadata", {}),
            "location": item.get("location", {}),
        }
        for item in response.get("retrievalResults", [])
    ]
    return agent_response(event, {"results": results})


def equals_filter(filters: dict[str, Any]) -> dict[str, Any]:
    conditions = [{"equals": {"key": key, "value": value}} for key, value in filters.items() if value]
    if len(conditions) == 1:
        return conditions[0]
    return {"andAll": conditions}


def parse_body(event: dict[str, Any]) -> dict[str, Any]:
    request_body = event.get("requestBody", {}).get("content", {}).get("application/json", {}).get("properties", [])
    return {item["name"]: json.loads(item["value"]) if item.get("type") in {"array", "object"} else item.get("value") for item in request_body}


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
