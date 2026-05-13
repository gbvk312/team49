#!/usr/bin/env python3
import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

import boto3
from botocore.exceptions import ClientError


SAMPLE_3GPP = """# TS 38.331 Rel-18

## 5.5.4 Measurement Reporting

The UE evaluates event A3 and reports when a neighbouring cell becomes offset better than the serving cell.
This procedure references TS 38.300 and supports mobility robustness.

```asn1
MeasurementReport ::= SEQUENCE {
  criticalExtensions CHOICE {
    measurementReport-r8 MeasurementReport-r8-IEs
  }
}
```
"""

SAMPLE_WHITEPAPER = """# Nokia Private 5G Network Slicing Whitepaper

Nokia explains how private 5G deployments use Network Slicing and mobility measurements to preserve service quality.
The paper discusses Measurement Reporting behavior already specified by 3GPP TS 38.331 and references TS 23.501.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed demo 3GPP and whitepaper content.")
    parser.add_argument("--raw-bucket", required=True, help="Raw corpus bucket from the CDK output.")
    parser.add_argument("--api-url", help="Optional API Gateway URL to verify POST /ask.")
    args = parser.parse_args()

    s3 = boto3.client("s3")
    upload_text(s3, args.raw_bucket, "3GPP/marked/TS_38.331/Rel-18/measurement-reporting.md", SAMPLE_3GPP)
    upload_text(s3, args.raw_bucket, "whitepapers/nokia/private-5g-network-slicing.md", SAMPLE_WHITEPAPER)
    print("Uploaded demo corpus objects. EventBridge should start ingestion within a few seconds.")

    if args.api_url:
        time.sleep(5)
        result = ask(args.api_url, "Show Measurement Reporting in TS 38.331 Rel-18 and related whitepaper explanations")
        print(json.dumps(result, indent=2))
    return 0


def upload_text(s3, bucket: str, key: str, body: str) -> None:
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=body.encode("utf-8"),
        ContentType="text/markdown; charset=utf-8",
    )
    print(f"s3://{bucket}/{key}")


def ask(api_url: str, query: str) -> dict:
    payload = json.dumps({"query": query}).encode("utf-8")
    request = urllib.request.Request(
        f"{api_url.rstrip('/')}/ask",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ClientError as exc:
        print(f"AWS error: {exc}", file=sys.stderr)
        raise SystemExit(1)
