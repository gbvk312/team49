import json
import os
import re
from typing import Any

import boto3
from botocore.config import Config

s3 = boto3.client("s3")
bedrock = boto3.client(
    "bedrock-runtime",
    config=Config(retries={"total_max_attempts": 4, "mode": "adaptive"}, read_timeout=60),
)

FOUNDATION_MODEL = os.environ["FOUNDATION_MODEL"]
SPEC_RE = re.compile(r"\b(?:TS|TR)\s*(\d{2}\.\d{3})\b", re.IGNORECASE)
CLAUSE_RE = re.compile(r"\b(?:clause|section)\s+(\d+(?:\.\d+){0,5})\b", re.IGNORECASE)
ASN_IMPORT_RE = re.compile(r"\bIMPORTS\b(?P<body>.*?)\bFROM\b\s+(?P<module>[A-Za-z0-9-]+)", re.IGNORECASE | re.DOTALL)


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    chunks = event.get("chunks", [])
    edges = []
    nodes = []
    for chunk in chunks:
        metadata = chunk.get("metadata", {})
        chunk_id = chunk["chunk_id"]
        text = read_text(chunk["bucket"], chunk["key"])
        nodes.extend(nodes_for_chunk(chunk_id, metadata))
        edges.extend(regex_edges(chunk_id, metadata, text))
        if metadata.get("source_type") == "whitepaper":
            edges.extend(llm_whitepaper_edges(chunk_id, metadata, text[:8000]))

    relationship_key = f"relationships/{event.get('source_key') or event.get('key', 'input')}.json".replace("//", "/")
    s3.put_object(
        Bucket=event["bucket"],
        Key=relationship_key,
        Body=json.dumps({"nodes": dedupe(nodes), "edges": dedupe(edges)}, separators=(",", ":")).encode("utf-8"),
        ContentType="application/json",
    )
    return {**event, "relationship_key": relationship_key, "nodes": dedupe(nodes), "edges": dedupe(edges)}


def read_text(bucket: str, key: str) -> str:
    response = s3.get_object(Bucket=bucket, Key=key)
    try:
        return response["Body"].read().decode("utf-8")
    finally:
        response["Body"].close()


def nodes_for_chunk(chunk_id: str, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = [{"id": chunk_id, "label": metadata.get("feature") or metadata.get("section") or chunk_id, "type": "Chunk"}]
    if metadata.get("spec"):
        nodes.append({"id": metadata["spec"], "label": metadata["spec"], "type": "Spec"})
    if metadata.get("release"):
        nodes.append({"id": metadata["release"], "label": metadata["release"], "type": "Release"})
    if metadata.get("feature"):
        nodes.append({"id": feature_id(metadata), "label": metadata["feature"], "type": "Feature"})
    if metadata.get("vendor"):
        nodes.append({"id": metadata["vendor"], "label": metadata["vendor"], "type": "Vendor"})
    return nodes


def regex_edges(chunk_id: str, metadata: dict[str, Any], text: str) -> list[dict[str, Any]]:
    edges = []
    feature = feature_id(metadata)
    if metadata.get("spec"):
        edges.append(edge(feature, "DEFINED_IN", metadata["spec"], 1.0, chunk_id))
    if metadata.get("release") and metadata.get("spec"):
        edges.append(edge(metadata["spec"], "DEFINED_IN", metadata["release"], 1.0, chunk_id))
    if metadata.get("vendor") and feature:
        edges.append(edge(metadata["vendor"], "DEPLOYED_BY", feature, 0.8, chunk_id))
    for spec in sorted({f"TS {match}" for match in SPEC_RE.findall(text)}):
        if spec != metadata.get("spec"):
            edges.append(edge(feature or chunk_id, "REFERENCES", spec, 1.0, chunk_id))
    for clause in sorted(set(CLAUSE_RE.findall(text))):
        edges.append(edge(feature or chunk_id, "REFERENCES", f"{metadata.get('spec', 'section')}#{clause}", 0.9, chunk_id))
    for match in ASN_IMPORT_RE.finditer(text):
        body = " ".join(match.group("body").split())
        module = match.group("module")
        edges.append(edge(feature or chunk_id, "IMPORTS", module, 1.0, chunk_id, {"symbols": body[:500]}))
    return edges


def llm_whitepaper_edges(chunk_id: str, metadata: dict[str, Any], text: str) -> list[dict[str, Any]]:
    prompt = f"""
Identify relationships from this telecom whitepaper chunk to 3GPP-defined features.
Return only a JSON array of edges with fields:
subject, predicate, object, confidence, evidence.

Allowed predicates: EXPLAINS, RELATED_TO, DEPLOYED_BY.
Only include edges with confidence >= 0.7.

Metadata:
{json.dumps(metadata)}

Chunk:
<chunk>
{text}
</chunk>
""".strip()
    response = bedrock.converse(
        modelId=FOUNDATION_MODEL,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 1600, "temperature": 0},
    )
    raw = response["output"]["message"]["content"][0]["text"]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        parsed = json.loads(match.group(0)) if match else []
    return [
        edge(item["subject"], item["predicate"], item["object"], float(item.get("confidence", 0.7)), chunk_id, {"evidence": item.get("evidence", "")})
        for item in parsed
        if item.get("subject") and item.get("object") and float(item.get("confidence", 0)) >= 0.7
    ]


def feature_id(metadata: dict[str, Any]) -> str:
    feature = metadata.get("feature") or metadata.get("section") or "unknown"
    return "#".join([metadata.get("spec", "unknown").replace(" ", "_"), metadata.get("section", ""), slug(feature)]).strip("#")


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def edge(subject: str, predicate: str, obj: str, confidence: float, chunk_id: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": slug(f"{subject}-{predicate}-{obj}-{chunk_id}"), "source": subject, "target": obj, "type": predicate, "confidence": confidence, "chunk_id": chunk_id, **(extra or {})}


def dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {item["id"]: item for item in items if item.get("id")}
    return list(by_id.values())
