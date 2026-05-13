import os
from typing import Any

import boto3

bedrock_agent = boto3.client("bedrock-agent")

KNOWLEDGE_BASE_ID = os.environ["KNOWLEDGE_BASE_ID"]
DATA_SOURCE_ID = os.environ["DATA_SOURCE_ID"]


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    response = bedrock_agent.start_ingestion_job(
        knowledgeBaseId=KNOWLEDGE_BASE_ID,
        dataSourceId=DATA_SOURCE_ID,
        description=f"Ingest chunks for {event.get('source_key') or event.get('key')}",
    )
    return {**event, "ingestion_job": response["ingestionJob"]}
