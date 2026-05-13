import hashlib
import json
import os
import re
from typing import Any

import boto3

s3 = boto3.client("s3")

OUTPUT_BUCKET = os.environ["CHUNKS_BUCKET"]
MAX_CHUNK_CHARS = int(os.environ.get("MAX_CHUNK_CHARS", "8000"))


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
SECTION_RE = re.compile(r"\b(\d+(?:\.\d+){0,5})\b")
SPEC_RE = re.compile(r"\b(?:TS|TR)\s*(\d{2}\.\d{3})\b", re.IGNORECASE)
RELEASE_RE = re.compile(r"\bRel(?:ease)?[-\s]?(\d{2})\b", re.IGNORECASE)
ASN1_RE = re.compile(r"::=\s*(SEQUENCE|CHOICE|ENUMERATED|INTEGER|BOOLEAN|OCTET STRING)", re.IGNORECASE)


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    bucket = event.get("bucket") or event.get("detail", {}).get("bucket", {}).get("name")
    key = event.get("key") or event.get("detail", {}).get("object", {}).get("key")
    if not bucket or not key:
        raise ValueError("event must contain bucket and key")

    markdown = read_text(bucket, key)
    base_metadata = event.get("metadata") or infer_metadata(key, markdown)
    chunks = build_chunks(markdown, base_metadata)

    written = []
    for index, chunk in enumerate(chunks):
        chunk_id = stable_chunk_id(base_metadata, chunk["section"], index, chunk["text"])
        metadata = {
            **base_metadata,
            **chunk["metadata"],
            "chunk_id": chunk_id,
            "embedding_id": chunk_id,
            "s3_source": f"s3://{bucket}/{key}",
        }
        object_key = f"chunks/{chunk_id}.txt"
        s3.put_object(
            Bucket=OUTPUT_BUCKET,
            Key=object_key,
            Body=chunk["text"].encode("utf-8"),
            ContentType="text/plain; charset=utf-8",
        )
        s3.put_object(
            Bucket=OUTPUT_BUCKET,
            Key=f"{object_key}.metadata.json",
            Body=json.dumps({"metadataAttributes": metadata}, separators=(",", ":")).encode("utf-8"),
            ContentType="application/json",
        )
        written.append(
            {
                "chunk_id": chunk_id,
                "bucket": OUTPUT_BUCKET,
                "key": object_key,
                "metadata": metadata,
                "text_preview": chunk["text"][:500],
            }
        )

    return {**event, "chunks": written, "chunk_count": len(written)}


def read_text(bucket: str, key: str) -> str:
    response = s3.get_object(Bucket=bucket, Key=key)
    try:
        return response["Body"].read().decode("utf-8")
    finally:
        response["Body"].close()


def infer_metadata(key: str, text: str) -> dict[str, Any]:
    source_type = "whitepaper" if key.lower().startswith("whitepapers/") else "3gpp"
    spec_match = SPEC_RE.search(key) or SPEC_RE.search(text[:4000])
    release_match = RELEASE_RE.search(key) or RELEASE_RE.search(text[:4000])
    return {
        "source_type": source_type,
        "spec": f"TS {spec_match.group(1)}" if spec_match else "",
        "release": f"Rel-{release_match.group(1)}" if release_match else "",
        "section": "",
        "feature": "",
        "keywords": [],
        "references": [],
    }


def build_chunks(markdown: str, base_metadata: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = split_by_semantic_boundaries(markdown)
    chunks: list[dict[str, Any]] = []
    for block in blocks:
        for part in split_large_block(block["text"], MAX_CHUNK_CHARS):
            metadata = extract_chunk_metadata(part, base_metadata, block)
            chunks.append({"text": part.strip(), "section": metadata.get("section", ""), "metadata": metadata})
    return [chunk for chunk in chunks if chunk["text"]]


def split_by_semantic_boundaries(markdown: str) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    current: list[str] = []
    current_heading = ""
    in_fence = False
    fence_lines: list[str] = []

    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            fence_lines.append(line)
            if not in_fence:
                fenced_text = "\n".join(fence_lines)
                if "asn1" in fence_lines[0].lower() or ASN1_RE.search(fenced_text):
                    flush(blocks, current, current_heading)
                    blocks.append({"heading": "ASN.1 block", "text": fenced_text})
                    fence_lines = []
                    continue
                current.extend(fence_lines)
                fence_lines = []
            continue
        if in_fence:
            fence_lines.append(line)
            continue

        heading = HEADING_RE.match(line)
        is_procedure = stripped.lower().startswith(("procedure", "signalling flow", "signaling flow"))
        is_feature = "feature" in stripped.lower() and stripped.endswith(":")
        if heading or is_procedure or is_feature:
            flush(blocks, current, current_heading)
            current_heading = heading.group(2) if heading else stripped.rstrip(":")
        current.append(line)

    flush(blocks, current, current_heading)
    return blocks


def flush(blocks: list[dict[str, str]], current: list[str], heading: str) -> None:
    text = "\n".join(current).strip()
    if text:
        blocks.append({"heading": heading, "text": text})
    current.clear()


def split_large_block(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    paragraphs = re.split(r"\n\s*\n", text)
    parts: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip()
        if len(candidate) > limit and current:
            parts.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def extract_chunk_metadata(text: str, base_metadata: dict[str, Any], block: dict[str, str]) -> dict[str, Any]:
    section_match = SECTION_RE.search(block.get("heading", "")) or SECTION_RE.search(text[:500])
    references = sorted({f"TS {match}" for match in SPEC_RE.findall(text)})
    feature = block.get("heading") or base_metadata.get("feature", "")
    return {
        "spec": base_metadata.get("spec", ""),
        "release": base_metadata.get("release", ""),
        "section": section_match.group(1) if section_match else base_metadata.get("section", ""),
        "feature": feature,
        "keywords": sorted(set(base_metadata.get("keywords", []))),
        "references": references or base_metadata.get("references", []),
        "source_type": base_metadata.get("source_type", "3gpp"),
    }


def stable_chunk_id(metadata: dict[str, Any], section: str, index: int, text: str) -> str:
    raw = "|".join(
        [
            metadata.get("spec", ""),
            metadata.get("release", ""),
            section,
            str(index),
            hashlib.sha1(text.encode("utf-8")).hexdigest()[:12],
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()
