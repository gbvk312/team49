#!/usr/bin/env python3
"""Create the AOSS vector index after the collection is deployed.

Usage:
    python scripts/create_vector_index.py --endpoint <COLLECTION_ENDPOINT> --region <REGION>
"""
import argparse
import json
import socket
import time
import urllib.request

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest


def request(method, url, payload, region, ignore_statuses):
    session = boto3.Session()
    body = json.dumps(payload).encode("utf-8") if payload is not None else b""
    creds = session.get_credentials().get_frozen_credentials()
    aws_request = AWSRequest(method=method, url=url, data=body, headers={"Content-Type": "application/json"})
    SigV4Auth(creds, "aoss", region).add_auth(aws_request)
    http_request = urllib.request.Request(url, data=body or None, headers=dict(aws_request.headers), method=method)
    try:
        with urllib.request.urlopen(http_request, timeout=30) as response:
            return {"status": response.status, "body": response.read().decode("utf-8")}
    except urllib.error.HTTPError as exc:
        if exc.code in ignore_statuses:
            return {"status": exc.code, "body": exc.read().decode("utf-8")}
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--index-name", default="bedrock-knowledge-base-default-index")
    args = parser.parse_args()

    endpoint = args.endpoint.rstrip("/")
    mapping = {
        "settings": {"index": {"knn": True}},
        "mappings": {
            "properties": {
                "bedrock-knowledge-base-default-vector": {
                    "type": "knn_vector",
                    "dimension": 1024,
                    "method": {"name": "hnsw", "engine": "faiss", "space_type": "cosinesimil"},
                },
                "AMAZON_BEDROCK_TEXT_CHUNK": {"type": "text"},
                "AMAZON_BEDROCK_METADATA": {"type": "object", "enabled": True},
            }
        },
    }

    print(f"Creating index '{args.index_name}' on {endpoint}")
    for attempt in range(60):
        try:
            result = request("PUT", f"{endpoint}/{args.index_name}", mapping, args.region, {200, 201, 400, 403})
            if result["status"] in {200, 201}:
                print(f"  Index created successfully on attempt {attempt}")
                return
            if result["status"] == 400:
                if "already exists" in result["body"].lower() or "resource_already_exists" in result["body"].lower():
                    print(f"  Index already exists")
                    return
                print(f"  400 response: {result['body'][:300]}")
                return
            if result["status"] == 403:
                print(f"  Attempt {attempt}: 403 - waiting for access policy propagation...")
        except (urllib.error.URLError, socket.timeout, OSError) as e:
            print(f"  Attempt {attempt}: connection error: {e}")
        time.sleep(10)
    raise SystemExit("ERROR: Still getting 403 after 10 minutes. Check AOSS data access policy.")


if __name__ == "__main__":
    main()
