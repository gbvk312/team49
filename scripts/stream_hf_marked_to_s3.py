"""
Stream GSMA/3GPP dataset files from Hugging Face (curl) to S3 without huggingface_hub TLS.
Uses Hub tree API with Link pagination, then curl | aws s3 cp for each file.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse


REPO = "GSMA/3GPP"
BASE_TREE = f"https://huggingface.co/api/datasets/{REPO}/tree/main"
RESOLVE = f"https://huggingface.co/datasets/{REPO}/resolve/main"

REL_RE = re.compile(r"^marked/Rel-(8|9|10|11|12|13|14|15|16|17|18|19)/")


def fetch_page(url: str) -> tuple[list[dict], str | None]:
    hpath = tempfile.mktemp(suffix=".hdr")
    bpath = tempfile.mktemp(suffix=".json")
    try:
        subprocess.run(
            ["curl", "-fsSL", url, "-D", hpath, "-o", bpath],
            check=True,
        )
        with open(bpath, encoding="utf-8") as f:
            data = json.load(f)
        with open(hpath, encoding="utf-8", errors="replace") as f:
            headers = f.read()
        next_url = None
        for line in headers.splitlines():
            if line.lower().startswith("link:"):
                for segment in line[5:].split(","):
                    if 'rel="next"' in segment:
                        m = re.search(r"<([^>]+)>", segment)
                        if m:
                            next_url = m.group(1)
        return data, next_url
    finally:
        for p in (hpath, bpath):
            try:
                os.remove(p)
            except OSError:
                pass


def iter_files_for_release(rel: int):
    """Yield file rows (type file) under marked/Rel-{rel}/ (paginated)."""
    url = f"{BASE_TREE}/marked/Rel-{rel}?recursive=true&limit=1000"
    while url:
        rows, url = fetch_page(url)
        for row in rows:
            if row.get("type") != "file":
                continue
            p = row.get("path", "").replace("\\", "/")
            if REL_RE.match(p):
                yield row


def s3_key_for_repo_path(prefix: str, repo_path: str) -> str:
    return f"{prefix.rstrip('/')}/{repo_path}"


def list_existing_keys_for_prefix(
    bucket: str,
    key_prefix: str,
    profile: str,
    region: str,
) -> set[str]:
    """All object keys under key_prefix (paginated list-objects-v2)."""
    keys: set[str] = set()
    token: str | None = None
    while True:
        cmd = [
            "aws",
            "s3api",
            "list-objects-v2",
            "--bucket",
            bucket,
            "--prefix",
            key_prefix,
            "--profile",
            profile,
            "--region",
            region,
            "--output",
            "json",
            "--max-keys",
            "1000",
        ]
        if token:
            cmd.extend(["--continuation-token", token])
        raw = subprocess.check_output(cmd, text=True)
        d = json.loads(raw)
        for obj in d.get("Contents") or []:
            keys.add(obj["Key"])
        token = d.get("NextContinuationToken")
        if not token:
            break
    return keys


def stream_file_to_s3(
    repo_path: str,
    bucket: str,
    prefix: str,
    profile: str,
    region: str,
) -> None:
    enc = urllib.parse.quote(repo_path, safe="/")
    src = f"{RESOLVE}/{enc}"
    key = s3_key_for_repo_path(prefix, repo_path)
    dest = f"s3://{bucket}/{key}"
    curl = subprocess.Popen(
        ["curl", "-fsSL", src],
        stdout=subprocess.PIPE,
    )
    try:
        subprocess.run(
            [
                "aws",
                "s3",
                "cp",
                "-",
                dest,
                "--profile",
                profile,
                "--region",
                region,
            ],
            stdin=curl.stdout,
            check=True,
        )
    finally:
        if curl.stdout:
            curl.stdout.close()
        curl.wait()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", default="team49-715001841576")
    ap.add_argument(
        "--prefix",
        default="datasets/GSMA-3GPP",
        help="S3 key prefix; object keys are {prefix}/{repo_path}",
    )
    ap.add_argument("--profile", default="nokia-hack")
    ap.add_argument("--region", default="us-west-2")
    ap.add_argument("--releases", default="8-19", help='e.g. "8-19" or "19"')
    ap.add_argument("--max-files", type=int, default=0, help="0 = no limit (full upload)")
    ap.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip upload when the object key already exists in the bucket (one list per release).",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if "-" in args.releases and "," not in args.releases:
        a, b = args.releases.split("-", 1)
        rels = list(range(int(a), int(b) + 1))
    else:
        rels = [int(x) for x in args.releases.replace(",", " ").split() if x.strip()]

    total_done = 0
    total_skipped = 0
    total_bytes = 0
    t0 = time.time()
    for rel in rels:
        print(f"[upload] marked/Rel-{rel} ...", flush=True)
        rel_prefix = f"{args.prefix.rstrip('/')}/marked/Rel-{rel}/"
        existing: set[str] | None = None
        if args.skip_existing:
            print(f"  [skip-existing] listing s3://{args.bucket}/{rel_prefix} ...", flush=True)
            existing = list_existing_keys_for_prefix(
                args.bucket, rel_prefix, args.profile, args.region
            )
            print(f"  [skip-existing] found {len(existing)} object(s) already", flush=True)
        n_rel = 0
        for row in iter_files_for_release(rel):
            n_rel += 1
            path = row["path"]
            size = int(row.get("size") or 0)
            full_key = s3_key_for_repo_path(args.prefix, path)
            if existing is not None and full_key in existing:
                total_skipped += 1
                if total_skipped <= 5 or total_skipped % 500 == 0:
                    print(f"  SKIP (exists) {path}", flush=True)
                continue
            if args.max_files and total_done >= args.max_files:
                print("[stop] max-files reached", flush=True)
                dt = time.time() - t0
                print(
                    f"Done: uploaded={total_done} skipped={total_skipped} ~{total_bytes} bytes in {dt:.1f}s",
                    flush=True,
                )
                return 0
            if args.dry_run:
                print(f"  DRY {path} ({size} B)", flush=True)
            else:
                print(f"  UP {path} ({size} B)", flush=True)
                stream_file_to_s3(path, args.bucket, args.prefix, args.profile, args.region)
            total_done += 1
            total_bytes += size
        print(
            f"[upload] Rel-{rel}: seen {n_rel} file(s) on Hub; uploaded {total_done} cumulative; skipped {total_skipped} cumulative",
            flush=True,
        )
    dt = time.time() - t0
    print(
        f"Finished: uploaded={total_done} skipped={total_skipped} ~{total_bytes} bytes ({total_bytes / (1024**3):.3f} GiB) in {dt:.1f}s",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
