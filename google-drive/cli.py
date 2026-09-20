"""
drive-cli — Command-line client for the Google Drive system.
Usage: python cli.py <command> [args...]
Requires a running server (python __main__.py --server).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys

import httpx

BASE_URL = os.environ.get("DRIVE_SERVER", "http://127.0.0.1:9200")
TOKEN_FILE = os.environ.get("DRIVE_TOKEN_FILE", ".drive_token")


def _load_token() -> str | None:
    if os.path.exists(TOKEN_FILE):
        return open(TOKEN_FILE).read().strip()
    return None


def _save_token(token: str):
    with open(TOKEN_FILE, "w") as f:
        f.write(token)


def _headers() -> dict:
    token = _load_token()
    if not token:
        print("Not logged in. Run: python cli.py login <email> <password>")
        sys.exit(1)
    return {"Authorization": f"Bearer {token}"}


def cmd_register(args):
    r = httpx.post(f"{BASE_URL}/api/register", json={"email": args.email, "password": args.password})
    if r.status_code == 200:
        data = r.json()
        _save_token(data["token"])
        print(f"Registered: {data['user_id']}")
    else:
        print(f"Error: {r.json()}")


def cmd_login(args):
    r = httpx.post(f"{BASE_URL}/api/login", json={"email": args.email, "password": args.password})
    if r.status_code == 200:
        data = r.json()
        _save_token(data["token"])
        print(f"Logged in as {data['user_id']}")
    else:
        print(f"Error: {r.json()}")


def cmd_upload(args):
    filepath = args.filepath
    if not os.path.isfile(filepath):
        print(f"File not found: {filepath}")
        return

    data = open(filepath, "rb").read()
    file_name = os.path.basename(filepath)
    path = "/" + file_name

    # Split into blocks (use server's block_size — default 4MB, but get from stats or config)
    block_size = 4 * 1024 * 1024
    blocks = [data[i:i + block_size] for i in range(0, len(data), block_size)] or [b""]
    hashes = [hashlib.sha256(b).hexdigest() for b in blocks]

    # Start upload
    r = httpx.post(f"{BASE_URL}/api/files/upload", headers=_headers(), json={
        "file_name": file_name, "path": path, "size": len(data),
        "total_block_count": len(blocks), "block_hashes": hashes,
    })
    if r.status_code != 200:
        print(f"Upload start failed: {r.json()}")
        return
    resp = r.json()
    session_id = resp["session_id"]
    file_id = resp["file_id"]
    dedup_set = set(resp["deduplicated_hashes"])
    print(f"Session: {session_id}, File: {file_id}, Dedup hits: {len(dedup_set)}")

    # Upload missing blocks
    to_upload = [(h, b) for h, b in zip(hashes, blocks) if h not in dedup_set]
    batch_size = 10  # upload 10 blocks at a time
    for i in range(0, len(to_upload), batch_size):
        batch = to_upload[i:i + batch_size]
        payload = {
            "session_id": session_id,
            "blocks": [{"hash": h, "data_b64": base64.b64encode(b).decode()} for h, b in batch],
        }
        r = httpx.post(f"{BASE_URL}/api/blocks", headers=_headers(), json=payload)
        if r.status_code != 200:
            print(f"Block upload failed: {r.json()}")
            return
        print(f"  Uploaded blocks {i+1}-{i+len(batch)} / {len(to_upload)}")

    # Commit
    r = httpx.post(f"{BASE_URL}/api/files/{file_id}/commit", headers=_headers(), json={
        "session_id": session_id, "block_hashes": hashes,
    })
    if r.status_code == 200:
        result = r.json()
        print(f"Committed: version {result['version_no']}")
    else:
        print(f"Commit failed: {r.json()}")


def cmd_download(args):
    file_id = args.file_id
    output = args.output or file_id
    params = {}
    if args.version:
        params["version"] = args.version
    r = httpx.get(f"{BASE_URL}/api/files/{file_id}/download", headers=_headers(), params=params)
    if r.status_code == 200:
        with open(output, "wb") as f:
            f.write(r.content)
        print(f"Downloaded {len(r.content)} bytes -> {output}")
    else:
        print(f"Error: {r.json()}")


def cmd_list(args):
    r = httpx.get(f"{BASE_URL}/api/files/list", headers=_headers())
    if r.status_code != 200:
        print(f"Error: {r.json()}")
        return
    files = r.json()
    if not files:
        print("No files.")
        return
    print(f"{'FILE_ID':<20} {'NAME':<20} {'SIZE':<10} {'VER':<4} {'STATUS'}")
    print("-" * 70)
    for f in files:
        print(f"{f['file_id']:<20} {f['name']:<20} {f['size']:<10} {f['latest_version']:<4} {f['status']}")


def cmd_revisions(args):
    r = httpx.get(f"{BASE_URL}/api/files/{args.file_id}/revisions", headers=_headers())
    for rev in r.json():
        print(f"  v{rev['version_no']:>3} | {rev['size']:>10} bytes | {rev['created_at']} | by {rev['author_id']}")


def cmd_share(args):
    r = httpx.post(f"{BASE_URL}/api/files/{args.file_id}/share", headers=_headers(), json={
        "shared_with": args.email, "permission": args.permission,
    })
    if r.status_code == 200:
        print(f"Shared {args.file_id} with {args.email} ({args.permission})")
    else:
        print(f"Error: {r.json()}")


def cmd_notifications(args):
    params = {"wait": args.wait, "since": args.since}
    r = httpx.get(f"{BASE_URL}/api/notifications", headers=_headers(), params=params)
    events = r.json()
    if not events:
        print("No new notifications.")
    for e in events:
        print(f"  [{e['notif_id']}] {e['event']:>5} | file={e['file_id']} | {e['payload']}")


def cmd_stats(args):
    r = httpx.get(f"{BASE_URL}/api/stats")
    data = r.json()
    print(f"  Users:         {data['users']}")
    print(f"  Files:         {data['files']}")
    print(f"  Unique blocks: {data['unique_blocks']}")
    print(f"  Logical bytes: {data['logical_bytes']:,}")
    print(f"  Stored bytes:  {data['stored_bytes']:,}")
    saved = data['logical_bytes'] - data['stored_bytes']
    if saved > 0:
        print(f"  Dedup saved:   {saved:,} bytes ({100*saved/max(data['logical_bytes'],1):.1f}%)")


def cmd_gc(args):
    r = httpx.post(f"{BASE_URL}/api/admin/gc", headers=_headers())
    print(f"GC freed {r.json()['freed_blocks']} blocks")


def main():
    parser = argparse.ArgumentParser(prog="drive-cli", description="Google Drive CLI Client")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("register", help="Register new account")
    p.add_argument("email"); p.add_argument("password")

    p = sub.add_parser("login", help="Login")
    p.add_argument("email"); p.add_argument("password")

    p = sub.add_parser("upload", help="Upload a file")
    p.add_argument("filepath")

    p = sub.add_parser("download", help="Download a file")
    p.add_argument("file_id"); p.add_argument("output", nargs="?"); p.add_argument("--version", type=int)

    sub.add_parser("list", help="List files")

    p = sub.add_parser("revisions", help="List file revisions")
    p.add_argument("file_id")

    p = sub.add_parser("share", help="Share a file")
    p.add_argument("file_id"); p.add_argument("email"); p.add_argument("permission", nargs="?", default="view")

    p = sub.add_parser("notifications", help="Poll notifications")
    p.add_argument("--wait", type=float, default=5.0); p.add_argument("--since", type=int, default=0)

    sub.add_parser("stats", help="Show system stats")
    sub.add_parser("gc", help="Garbage collect orphan blocks")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    cmds = {
        "register": cmd_register, "login": cmd_login, "upload": cmd_upload,
        "download": cmd_download, "list": cmd_list, "revisions": cmd_revisions,
        "share": cmd_share, "notifications": cmd_notifications,
        "stats": cmd_stats, "gc": cmd_gc,
    }
    cmds[args.command](args)


if __name__ == "__main__":
    main()
