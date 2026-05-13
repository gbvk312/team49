import os
from typing import Any

import boto3

dynamodb = boto3.resource("dynamodb")
chunks_table = dynamodb.Table(os.environ["CHUNKS_TABLE"])
features_table = dynamodb.Table(os.environ["FEATURES_TABLE"])


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    chunks = event.get("chunks", [])
    with chunks_table.batch_writer() as chunk_batch:
        for chunk in chunks:
            metadata = chunk["metadata"]
            chunk_batch.put_item(
                Item={
                    "chunk_id": chunk["chunk_id"],
                    "spec_release": f"{metadata.get('spec', '')}#{metadata.get('release', '')}",
                    "section": metadata.get("section", ""),
                    "feature": metadata.get("feature", ""),
                    "source_type": metadata.get("source_type", ""),
                    "embedding_id": metadata.get("embedding_id", chunk["chunk_id"]),
                    "s3_bucket": chunk["bucket"],
                    "s3_key": chunk["key"],
                    "metadata": metadata,
                    "text_preview": chunk.get("text_preview", ""),
                }
            )

    with features_table.batch_writer() as feature_batch:
        seen = set()
        for chunk in chunks:
            metadata = chunk["metadata"]
            feature_id = make_feature_id(metadata)
            if feature_id in seen:
                continue
            seen.add(feature_id)
            feature_batch.put_item(
                Item={
                    "feature_id": feature_id,
                    "feature": metadata.get("feature", ""),
                    "spec": metadata.get("spec", ""),
                    "release": metadata.get("release", ""),
                    "section": metadata.get("section", ""),
                    "keywords": metadata.get("keywords", []),
                    "references": metadata.get("references", []),
                    "related_specs": metadata.get("related_specs", []),
                    "source_type": metadata.get("source_type", ""),
                }
            )

    return {**event, "metadata_written": len(chunks)}


def make_feature_id(metadata: dict[str, Any]) -> str:
    feature = (metadata.get("feature") or metadata.get("section") or "unknown").lower()
    safe_feature = "".join(ch if ch.isalnum() else "_" for ch in feature).strip("_")
    return "#".join([metadata.get("spec", "unknown").replace(" ", "_"), metadata.get("section", ""), safe_feature]).strip("#")
