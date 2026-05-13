import json
import os
import posixpath
import re
from typing import Any
from urllib.parse import unquote_plus

import boto3

s3 = boto3.client("s3")
textract = boto3.client("textract")

OUTPUT_BUCKET = os.environ["CHUNKS_BUCKET"]
IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    bucket, key = parse_s3_location(event)
    markdown = read_text(bucket, key)

    image_refs = IMAGE_RE.findall(markdown)
    enrichments = []
    for image_ref in image_refs:
        image_key = resolve_image_key(key, image_ref)
        extracted_text = analyze_image(bucket, image_key)
        if extracted_text:
            enrichments.append({"image": image_ref, "image_key": image_key, "text": extracted_text})
            markdown = markdown.replace(
                f"]({image_ref})",
                f"]({image_ref})\n\n> Textract image text from `{image_ref}`:\n>\n{quote_lines(extracted_text)}\n",
                1,
            )

    enriched_key = f"enriched/{key}"
    s3.put_object(
        Bucket=OUTPUT_BUCKET,
        Key=enriched_key,
        Body=markdown.encode("utf-8"),
        ContentType="text/markdown; charset=utf-8",
    )
    return {
        "source_bucket": bucket,
        "source_key": key,
        "bucket": OUTPUT_BUCKET,
        "key": enriched_key,
        "textract_images": enrichments,
    }


def parse_s3_location(event: dict[str, Any]) -> tuple[str, str]:
    if event.get("bucket") and event.get("key"):
        return event["bucket"], event["key"]
    if event.get("detail"):
        return event["detail"]["bucket"]["name"], unquote_plus(event["detail"]["object"]["key"])
    record = event["Records"][0]
    return record["s3"]["bucket"]["name"], unquote_plus(record["s3"]["object"]["key"])


def read_text(bucket: str, key: str) -> str:
    response = s3.get_object(Bucket=bucket, Key=key)
    try:
        return response["Body"].read().decode("utf-8")
    finally:
        response["Body"].close()


def resolve_image_key(markdown_key: str, image_ref: str) -> str:
    if image_ref.startswith("s3://"):
        return image_ref.split("/", 3)[-1]
    if image_ref.startswith(("http://", "https://")):
        raise ValueError(f"remote image refs are not supported for Textract: {image_ref}")
    return posixpath.normpath(posixpath.join(posixpath.dirname(markdown_key), image_ref))


def analyze_image(bucket: str, key: str) -> str:
    try:
        result = textract.analyze_document(
            Document={"S3Object": {"Bucket": bucket, "Name": key}},
            FeatureTypes=["TABLES", "FORMS"],
        )
    except textract.exceptions.UnsupportedDocumentException:
        return ""
    lines = [
        block["Text"]
        for block in result.get("Blocks", [])
        if block.get("BlockType") == "LINE" and block.get("Text")
    ]
    return "\n".join(lines)


def quote_lines(text: str) -> str:
    return "\n".join(f"> {line}" for line in text.splitlines())
