"""
Google Drive System — Entry Point

Usage:
    python __main__.py --server          # Run API server
    python __main__.py --demo            # Run end-to-end demo
    python __main__.py --cli <args...>   # Forward to drive-cli
"""
import argparse
import asyncio
import base64
import hashlib
import json
import logging
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.config import DriveConfig
from app.database import Database
from app.object_store import ObjectStore
from app.block_server import BlockServer
from app.notification import NotificationCenter
from app.api_service import ApiService, ConflictError, PermissionDeniedError, QuotaExceededError


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)


# ─── Demo ─────────────────────────────────────────────────────────────

async def run_demo():
    """Run a comprehensive end-to-end demo of the Google Drive system."""
    print("=" * 65)
    print("  GOOGLE DRIVE SYSTEM — DEMO")
    print("=" * 65)

    # Use a temp directory for the demo
    demo_dir = Path("data/demo-run")
    if demo_dir.exists():
        shutil.rmtree(demo_dir)

    config = DriveConfig()
    config.data_dir = demo_dir
    config.block_size = 50  # tiny blocks for demo visibility

    db = Database(config)
    await db.initialize()
    store = ObjectStore(config)
    bs = BlockServer(config, store)
    nc = NotificationCenter(db)
    svc = ApiService(config, db, bs, store, nc)

    try:
        # [1] Register users
        print("\n[1] Registering users...")
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        await db.insert_user("u_alice", "alice@example.com", "h1", "s1", config.default_quota_bytes, now)
        await db.insert_user("u_bob", "bob@example.com", "h2", "s2", config.default_quota_bytes, now)
        print("    ✓ alice@example.com (u_alice)")
        print("    ✓ bob@example.com   (u_bob)")

        # [2] Upload multi-block file
        print("\n[2] Alice uploads a 120-byte file (blocks of 50 bytes = 3 blocks)...")
        data = b"A" * 50 + b"B" * 50 + b"C" * 20  # 120 bytes = 3 blocks
        hashes, blocks = bs.split(data)
        print(f"    Block hashes: {[h[:8] + '...' for h in hashes]}")

        sid, fid, dedup = await svc.start_upload("u_alice", "report.bin", "/report.bin", len(data), len(hashes), block_hashes=hashes)
        print(f"    Session: {sid}, File: {fid}")

        # Upload blocks (all missing first time)
        block_payloads = [{"hash": h, "data_b64": base64.b64encode(b).decode()} for h, b in zip(hashes, blocks)]
        received = await svc.upload_blocks(sid, block_payloads)
        print(f"    Uploaded {len(received)} blocks")

        version_no = await svc.commit("u_alice", sid, fid, hashes)
        print(f"    ✓ Committed as version {version_no}")

        # [3] Dedup demonstration — upload identical content
        print("\n[3] Alice uploads identical content as new file (dedup test)...")
        sid2, fid2, dedup2 = await svc.start_upload("u_alice", "copy.bin", "/copy.bin", len(data), len(hashes), block_hashes=hashes)
        print(f"    Dedup hits at start: {len(dedup2)} blocks already known")
        # Upload only missing (none — all deduped)
        received2 = await svc.upload_blocks(sid2, [])  # nothing to upload!
        v2 = await svc.commit("u_alice", sid2, fid2, hashes)
        print(f"    ✓ Committed copy as version {v2} with 0 bytes uploaded (full dedup!)")

        # [4] Download & verify
        print("\n[4] Download and verify integrity...")
        downloaded = await svc.download("u_alice", fid)
        assert downloaded == data, "Download mismatch!"
        print(f"    ✓ Downloaded {len(downloaded)} bytes — hash verified: {bs.compute_hash(downloaded)[:16]}...")

        # [5] Revision history
        print("\n[5] Upload a new version (edit)...")
        data_v2 = b"X" * 50 + b"B" * 50 + b"C" * 20  # changed first block only
        hashes_v2, blocks_v2 = bs.split(data_v2)
        sid3, _, dedup3 = await svc.start_upload("u_alice", "report.bin", "/report.bin", len(data_v2), len(hashes_v2), file_id=fid, block_hashes=hashes_v2)
        missing_before = bs.which_hashes_missing(hashes_v2)
        print(f"    Delta: {len(hashes_v2)} total blocks, {len(missing_before)} need upload (rest deduped)")
        to_upload = [{"hash": h, "data_b64": base64.b64encode(b).decode()} for h, b in zip(hashes_v2, blocks_v2) if h in set(missing_before)]
        await svc.upload_blocks(sid3, to_upload)
        v3 = await svc.commit("u_alice", sid3, fid, hashes_v2)
        print(f"    ✓ Version {v3} committed (block 1 changed, blocks 2-3 reused)")

        revisions = await svc.list_revisions(fid)
        print(f"    Revision history: {[(r['version_no'], r['size']) for r in revisions]}")

        # [6] Sharing
        print("\n[6] Alice shares report with Bob (view)...")
        await svc.share("u_alice", fid, "bob@example.com", "view")
        bob_data = await svc.download("u_bob", fid)
        print(f"    ✓ Bob downloaded {len(bob_data)} bytes via share")

        # [7] Sync conflict
        print("\n[7] Sync conflict scenario...")
        # Bob tries to edit (he only has v{v3} as base, but makes different content)
        bob_data_v = b"BOB" * 16 + b"C" * 12  # different from alice's v3
        bob_hashes, bob_blocks = bs.split(bob_data_v)
        sid_bob, _, _ = await svc.start_upload("u_bob", "report.bin", "/report.bin", len(bob_data_v), len(bob_hashes), file_id=fid, base_version=v3, block_hashes=bob_hashes)
        await svc.upload_blocks(sid_bob, [{"hash": h, "data_b64": base64.b64encode(b).decode()} for h, b in zip(bob_hashes, bob_blocks)])
        # Bob commits — this creates a new version (since Bob shares same file_id, simulating conflict scenario):
        bob_v = await svc.commit("u_bob", sid_bob, fid, bob_hashes)
        print(f"    Bob committed version {bob_v} (concurrent edit)")

        # Simulate: Alice had base_version=v3 but server is now v{bob_v}
        sync_result = await svc.sync("u_alice", [{"file_id": fid, "base_version": v3, "block_hashes": hashes_v2}])
        if sync_result["conflicts"]:
            c = sync_result["conflicts"][0]
            print(f"    ⚠ Conflict detected! Alice base={c['client_base_version']}, server={c['server_version']}")
            # Alice resolves by override
            resolved_v = await svc.resolve("u_alice", fid, "override", hashes_v2)
            print(f"    ✓ Alice overrode → new version {resolved_v}")

        # [8] Notifications
        print("\n[8] Notifications for Bob...")
        events = await nc.poll("u_bob", since_id=0, wait=0.1)
        for e in events:
            print(f"    [{e['notif_id']}] {e['event']:>5} file={e['file_id']}")

        # [9] Stats
        print("\n[9] System statistics:")
        stats = await svc.get_stats()
        print(f"    Users: {stats['users']}, Files: {stats['files']}, Unique blocks: {stats['unique_blocks']}")
        print(f"    Logical bytes: {stats['logical_bytes']:,}, Stored bytes: {stats['stored_bytes']:,}")
        saved = stats['logical_bytes'] - stats['stored_bytes']
        if saved > 0:
            pct = 100 * saved / max(stats['logical_bytes'], 1)
            print(f"    Dedup saved: {saved:,} bytes ({pct:.1f}%)")

        print("\n" + "=" * 65)
        print("  DEMO COMPLETE")
        print("=" * 65)

    finally:
        await db.close()


# ─── Server ───────────────────────────────────────────────────────────

async def run_server():
    import uvicorn
    from app.server import app

    config = DriveConfig()
    print(f"Starting Google Drive Server on {config.host}:{config.port}")
    uvicorn.run(app, host=config.host, port=config.port)


# ─── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Google Drive System")
    parser.add_argument("--server", action="store_true", help="Run API server")
    parser.add_argument("--demo", action="store_true", help="Run end-to-end demo")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument("--cli", nargs=argparse.REMAINDER, help="Forward to drive-cli")
    args = parser.parse_args()

    setup_logging(args.verbose)

    if args.server:
        asyncio.run(run_server())
    elif args.cli:
        sys.argv = ["drive-cli"] + args.cli
        from cli import main as cli_main
        cli_main()
    else:
        # Default: run demo
        asyncio.run(run_demo())


if __name__ == "__main__":
    main()
