import json
import os
from typing import Any

import boto3

runtime = boto3.client("bedrock-agent-runtime")
KNOWLEDGE_BASE_ID = os.environ["KNOWLEDGE_BASE_ID"]


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    body = parse_body(event)
    query = body.get("spec_or_feature") or body.get("query") or ""
    response = runtime.retrieve(
        knowledgeBaseId=KNOWLEDGE_BASE_ID,
        retrievalQuery={"text": query},
        retrievalConfiguration={
            "vectorSearchConfiguration": {
                "numberOfResults": int(body.get("top_k", 5)),
                "filter": {"equals": {"key": "source_type", "value": "whitepaper"}},
            }
        },
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


def parse_body(event: dict[str, Any]) -> dict[str, Any]:
    request_body = event.get("requestBody", {}).get("content", {}).get("application/json", {}).get("properties", [])
    return {item["name"]: item.get("value") for item in request_body}


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
