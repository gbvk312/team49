import json
import os
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr, Key

dynamodb = boto3.resource("dynamodb")
chunks_table = dynamodb.Table(os.environ["CHUNKS_TABLE"])
features_table = dynamodb.Table(os.environ["FEATURES_TABLE"])


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    params = parse_body(event)
    feature = params.get("feature")
    spec = params.get("spec")
    release = params.get("release")
    section = params.get("section")
    vendor = params.get("vendor")

    if feature:
        response = features_table.query(
            IndexName="by_feature_name",
            KeyConditionExpression=Key("feature").eq(feature),
        )
        items = response.get("Items", [])
    elif spec and section:
        response = features_table.query(
            IndexName="by_spec_section",
            KeyConditionExpression=Key("spec").eq(spec) & Key("section").begins_with(section),
        )
        items = response.get("Items", [])
    elif spec and release:
        response = chunks_table.query(
            IndexName="by_spec_release",
            KeyConditionExpression=Key("spec_release").eq(f"{spec}#{release}"),
        )
        items = response.get("Items", [])
    else:
        filter_expr = None
        for key, value in {"feature": feature, "spec": spec, "release": release, "vendor": vendor}.items():
            if value:
                expr = Attr("metadata.vendor").eq(value) if key == "vendor" else Attr(key).eq(value)
                filter_expr = expr if filter_expr is None else filter_expr & expr
        scan_kwargs = {"Limit": 25}
        if filter_expr is not None:
            scan_kwargs["FilterExpression"] = filter_expr
        items = chunks_table.scan(**scan_kwargs).get("Items", [])

    return agent_response(event, {"items": decimal_safe(items[:25])})


def parse_body(event: dict[str, Any]) -> dict[str, Any]:
    request_body = event.get("requestBody", {}).get("content", {}).get("application/json", {}).get("properties", [])
    return {item["name"]: item.get("value") for item in request_body}


def decimal_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


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
