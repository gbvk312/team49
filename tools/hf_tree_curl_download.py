"""List and download Hugging Face Hub files using curl only (no Python HTTPS)."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote


def curl_request(url: str) -> tuple[dict[str, str], bytes]:
    with tempfile.NamedTemporaryFile(delete=False) as hdr:
        hdr_path = hdr.name
    body_path = hdr_path + ".body"
    try:
        r = subprocess.run(
            ["curl", "-sS", "-L", "-D", hdr_path, "-o", body_path, url],
            check=False,
        )
        if r.returncode != 0:
            raise RuntimeError(f"curl failed ({r.returncode}) for {url}")
        raw_headers = Path(hdr_path).read_bytes()
        body = Path(body_path).read_bytes()
    finally:
        Path(hdr_path).unlink(missing_ok=True)
        Path(body_path).unlink(missing_ok=True)

    text = raw_headers.decode("utf-8", errors="replace")
    header_lines = text.split("\r\n") if "\r\n" in text else text.split("\n")
    headers: dict[str, str] = {}
    for line in header_lines:
        if ":" in line and not line.upper().startswith("HTTP/"):
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    return headers, body


def parse_next_link(headers: dict[str, str]) -> str | None:
    link = headers.get("link")
    if not link:
        return None
    for part in link.split(","):
        m = re.search(r"<([^>]+)>\s*;\s*rel=\"next\"", part.strip())
        if m:
            return m.group(1)
    return None


def iter_tree_files(repo_type: str, repo_id: str, revision: str, tree_path: str) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    encoded = quote(tree_path, safe="")
    base = f"https://huggingface.co/api/{repo_type}s/{repo_id}/tree/{revision}/{encoded}"
    url = f"{base}?expand=false&recursive=true&limit=1000"
    while url:
        headers, body = curl_request(url)
        ct = headers.get("content-type", "")
        if "application/json" not in ct.lower():
            raise RuntimeError(
                f"Unexpected content-type {ct!r} for {url!r}: {body[:500]!r}"
            )
        data = json.loads(body.decode("utf-8"))
        if not isinstance(data, list):
            raise RuntimeError(f"Expected list from tree API, got {type(data)}")
        for item in data:
            if item.get("type") == "file":
                files.append(item)
        url = parse_next_link(headers)
    return files


def download_file(repo_type: str, repo_id: str, revision: str, rel_path: str, dest_root: Path) -> None:
    dest = dest_root / rel_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    enc = "/".join(quote(p, safe="") for p in rel_path.split("/"))
    src = f"https://huggingface.co/{repo_type}s/{repo_id}/resolve/{revision}/{enc}"
    tmp = dest.with_suffix(dest.suffix + ".part")
    r = subprocess.run(
        ["curl", "-sS", "-L", "-f", "-o", str(tmp), src],
        check=False,
    )
    if r.returncode != 0:
        raise RuntimeError(f"curl download failed ({r.returncode}) {src}")
    tmp.replace(dest)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: hf_tree_curl_download.py <dest_dir>", file=sys.stderr)
        return 2
    dest = Path(sys.argv[1]).resolve()
    dest.mkdir(parents=True, exist_ok=True)

    repo_id = "GSMA/3GPP"
    revision = "main"
    for rel in range(8, 20):
        prefix = f"marked/Rel-{rel}"
        print(f"listing {prefix} ...", flush=True)
        files = iter_tree_files("dataset", repo_id, revision, prefix)
        print(f"  {len(files)} files", flush=True)
        for i, f in enumerate(files, 1):
            path = f["path"]
            if i == 1 or i % 200 == 0 or i == len(files):
                print(f"download [{rel}] [{i}/{len(files)}] {path}", flush=True)
            download_file("dataset", repo_id, revision, path, dest)

    print("done", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
