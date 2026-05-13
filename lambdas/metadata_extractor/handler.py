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
RELEASE_RE = re.compile(r"\bRel(?:ease)?[-\s]?(\d{2})\b", re.IGNORECASE)


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    bucket = event["bucket"]
    key = event["key"]
    markdown = read_text(bucket, key)
    source_type = "whitepaper" if key.lower().startswith(("enriched/whitepapers/", "whitepapers/")) else "3gpp"

    metadata = extract_metadata(markdown[:18000], key, source_type)
    metadata = normalize_metadata(metadata, key, markdown, source_type)
    metadata_key = f"metadata/{key}.json".replace("//", "/")
    s3.put_object(
        Bucket=bucket,
        Key=metadata_key,
        Body=json.dumps(metadata, separators=(",", ":")).encode("utf-8"),
        ContentType="application/json",
    )
    return {**event, "metadata": metadata, "metadata_key": metadata_key}


def read_text(bucket: str, key: str) -> str:
    response = s3.get_object(Bucket=bucket, Key=key)
    try:
        return response["Body"].read().decode("utf-8")
    finally:
        response["Body"].close()


def extract_metadata(text: str, key: str, source_type: str) -> dict[str, Any]:
    schema = (
        '{"source_type":"3gpp|whitepaper","spec":"TS 38.331","release":"Rel-18",'
        '"section":"5.5.4","feature":"Measurement Reporting","keywords":["A3"],'
        '"references":["TS 38.300"],"vendor":"Nokia","technology":"Network Slicing",'
        '"related_specs":["23.501"],"deployment_type":"Private 5G"}'
    )
    prompt = f"""
Extract metadata from this telecom corpus document.
Return only compact JSON matching this schema, omitting unknown optional fields:
{schema}

Rules:
- 3GPP markdown is the source of truth.
- Whitepapers explain features already defined by 3GPP; mark them as source_type=whitepaper.
- Normalize releases as Rel-18, Rel-17, etc.
- Normalize 3GPP specs as TS NN.NNN when known.

S3 key: {key}
Source type hint: {source_type}

Document excerpt:
<document>
{text}
</document>
""".strip()
    response = bedrock.converse(
        modelId=FOUNDATION_MODEL,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 1200, "temperature": 0},
    )
    output = response["output"]["message"]["content"][0]["text"]
    return parse_json_object(output)


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def normalize_metadata(metadata: dict[str, Any], key: str, markdown: str, source_type: str) -> dict[str, Any]:
    spec_match = SPEC_RE.search(key) or SPEC_RE.search(markdown[:4000])
    release_match = RELEASE_RE.search(key) or RELEASE_RE.search(markdown[:4000])
    metadata.setdefault("source_type", source_type)
    metadata["source_type"] = source_type
    metadata.setdefault("spec", f"TS {spec_match.group(1)}" if spec_match else "")
    metadata.setdefault("release", f"Rel-{release_match.group(1)}" if release_match else "")
    metadata.setdefault("section", "")
    metadata.setdefault("feature", "")
    metadata.setdefault("keywords", [])
    metadata.setdefault("references", [])
    metadata.setdefault("related_specs", [])
    return metadata
