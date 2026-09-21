"""
Core API Service — upload/commit/sync/conflict/download/share/GC/stats.
Orchestrates block_server for content, database for metadata, notification for events.
"""
from __future__ import annotations

import base64
import json
import secrets
import time

from .block_server import BlockServer
from .config import DriveConfig
from .database import Database
from .notification import NotificationCenter
from .object_store import ObjectStore


class ConflictError(Exception):
    """Raised when optimistic concurrency detects a version conflict."""
    def __init__(self, file_id: str, client_base: int, server_version: int, server_hashes: list[str]):
        self.file_id = file_id
        self.client_base = client_base
        self.server_version = server_version
        self.server_hashes = server_hashes
        super().__init__(f"Conflict on {file_id}: base={client_base} server={server_version}")


class QuotaExceededError(Exception):
    pass


class PermissionDeniedError(Exception):
    pass


class ApiService:
    def __init__(self, config: DriveConfig, db: Database,
                 block_server: BlockServer, object_store: ObjectStore,
                 notifier: NotificationCenter):
        self._config = config
        self._db = db
        self._block_server = block_server
        self._object_store = object_store
        self._notifier = notifier

    # ─── Upload ───────────────────────────────────────────────────────

    async def start_upload(self, user_id: str, file_name: str, path: str,
                           size: int, total_block_count: int,
                           file_id: str | None = None,
                           base_version: int | None = None,
                           block_hashes: list[str] | None = None) -> tuple[str, str, list[str]]:
        """Create upload session. Returns (session_id, file_id, deduplicated_hashes)."""
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        if file_id:
            # Editing existing file
            existing = await self._db.get_file(file_id)
            if not existing:
                raise FileNotFoundError(f"File {file_id} not found")
        else:
            # New file
            file_id = f"f_{secrets.token_hex(8)}"
            namespace = f"ns_{user_id}"
            await self._db.insert_file(file_id, user_id, file_name, path, namespace, now, now)

        session_id = f"s_{secrets.token_hex(8)}"
        await self._db.create_session(session_id, file_id, user_id,
                                      total_block_count, now, now)

        # Pre-check dedup: which declared hashes does the server already have?
        dedup = []
        if block_hashes:
            dedup = [h for h in block_hashes if self._object_store.exists(h)]

        return session_id, file_id, dedup

    async def upload_blocks(self, session_id: str, blocks: list[dict]) -> list[str]:
        """
        Receive blocks [{hash, data_b64}]. Store only those not already present (dedup).
        Update session received_hashes. Returns list of accepted hashes.
        """
        session = await self._db.get_session(session_id)
        if not session:
            raise FileNotFoundError(f"Session {session_id} not found")

        received = json.loads(session["received_hashes"])
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        for block in blocks:
            h = block["hash"]
            data = base64.b64decode(block["data_b64"])
            # Verify integrity
            computed = self._block_server.compute_hash(data)
            if computed != h:
                raise ValueError(f"Block hash mismatch for {h}")
            self._object_store.put_if_absent(h, data)
            if h not in received:
                received.append(h)

        state = "uploading" if len(received) < session["total_block_count"] else "uploading"
        await self._db.update_session(session_id, json.dumps(received), state, now)
        return received

    async def get_session_status(self, session_id: str) -> dict:
        """Return session state for resumable upload client polling."""
        session = await self._db.get_session(session_id)
        if not session:
            raise FileNotFoundError(f"Session {session_id} not found")
        received = json.loads(session["received_hashes"])
        missing = session["total_block_count"] - len(received)
        return {
            "session_id": session_id,
            "received_hashes": received,
            "missing_count": max(0, missing),
            "state": session["state"],
        }

    async def commit(self, user_id: str, session_id: str, file_id: str,
                     block_hashes: list[str]) -> int:
        """
        Finalize upload: enforce quota, write version, update file, notify.
        Returns new version_no.
        """
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Verify all blocks present
        missing = self._block_server.which_hashes_missing(block_hashes)
        if missing:
            raise ConflictError(f"Blocks still missing: {missing}", 0, 0, [])

        file = await self._db.get_file(file_id)
        if not file:
            raise FileNotFoundError(f"File {file_id} not found")

        # Conflict detection for edits
        session = await self._db.get_session(session_id)
        base_version = file["latest_version"]  # default: current server version

        if file["latest_version"] > 0 and session:
            # If this is an edit, check if client's base matches server
            # base_version is stored implicitly via the file's current state at session start
            pass  # detailed conflict logic in sync()

        # Quota check: compute new_unique_bytes (blocks not already counted for this user)
        new_unique_bytes = 0
        for h in block_hashes:
            existing_block = await self._db.get_block(h)
            if existing_block is None:
                # Brand new block
                data = self._object_store.get(h)
                new_unique_bytes += len(data) if data else 0

        user = await self._db.get_user_by_id(user_id)
        if user and user["used_bytes"] + new_unique_bytes > user["quota_bytes"]:
            raise QuotaExceededError("Storage quota exceeded")

        # Write version
        version_no = file["latest_version"] + 1
        version_id = f"v_{secrets.token_hex(6)}"
        total_size = sum(len(self._object_store.get(h) or b"") for h in block_hashes)
        await self._db.insert_version(version_id, file_id, version_no,
                                      json.dumps(block_hashes), total_size, user_id, now)

        # Update file record
        await self._db.update_file_version(file_id, version_no, total_size, "uploaded", now)

        # Insert/update block metadata + ref_count
        for h in block_hashes:
            data = self._object_store.get(h)
            blk_size = len(data) if data else 0
            existing = await self._db.get_block(h)
            if existing:
                await self._db.increment_block_ref(h)
            else:
                await self._db.insert_block(h, blk_size, now)

        # Update user quota
        await self._db.update_user_used_bytes(user_id, new_unique_bytes)

        # Update session state
        if session:
            await self._db.update_session(session_id, session["received_hashes"], "committed", now)

        # Notify relevant users (owner + shared users)
        event = "add" if version_no == 1 else "edit"
        await self._notifier.publish(user_id, file_id, event, {"name": file["name"], "version": version_no})
        # Notify shareholders
        shares = await self._db.fetch_all("SELECT shared_with FROM shares WHERE file_id=?", (file_id,))
        for s in shares:
            await self._notifier.publish(s["shared_with"], file_id, event, {"name": file["name"], "version": version_no})

        return version_no

    # ─── Download ─────────────────────────────────────────────────────

    async def download(self, user_id: str, file_id: str, version: int | None = None) -> bytes:
        """Reassemble file from blocks. Requires ownership or view share."""
        file = await self._db.get_file(file_id)
        if not file:
            raise FileNotFoundError(f"File {file_id} not found")

        # Permission check
        if file["user_id"] != user_id:
            share = await self._db.get_share(file_id, user_id)
            if not share:
                raise PermissionDeniedError("Access denied")

        target_version = version or file["latest_version"]
        ver = await self._db.get_version(file_id, target_version)
        if not ver:
            raise FileNotFoundError(f"Version {target_version} not found")

        hashes = json.loads(ver["block_hashes"])
        return self._block_server.reassemble(hashes)

    # ─── Sync & Conflict ──────────────────────────────────────────────

    async def sync(self, user_id: str, states: list[dict]) -> dict:
        """
        Client reports {file_id, base_version, block_hashes}.
        Server returns updates (client behind) or conflicts (concurrent edit).
        """
        updates = []
        conflicts = []

        for state in states:
            file = await self._db.get_file(state["file_id"])
            if not file:
                continue
            if file["user_id"] != user_id:
                share = await self._db.get_share(state["file_id"], user_id)
                if not share:
                    continue

            server_version = file["latest_version"]
            client_base = state["base_version"]

            if client_base == server_version:
                # Client is up to date — no update needed
                continue
            elif client_base < server_version:
                # Client is behind — check if client also has local changes
                client_hashes = state.get("block_hashes", [])
                ver = await self._db.get_version(state["file_id"], server_version)
                server_hashes = json.loads(ver["block_hashes"]) if ver else []

                if client_hashes and client_hashes != server_hashes:
                    # Conflict: client modified from an older base
                    conflicts.append({
                        "file_id": state["file_id"],
                        "client_base_version": client_base,
                        "server_version": server_version,
                        "server_block_hashes": server_hashes,
                    })
                else:
                    # Client just needs to pull
                    updates.append({
                        "file_id": state["file_id"],
                        "server_version": server_version,
                        "block_hashes": server_hashes,
                        "size": ver["size"] if ver else 0,
                    })

        return {"updates": updates, "conflicts": conflicts}

    async def resolve(self, user_id: str, file_id: str, action: str,
                      block_hashes: list[str] | None = None) -> int:
        """
        Resolve conflict: 'override' promotes client copy to new version,
        'keep' returns server version (no-op for data, just updates client state).
        """
        file = await self._db.get_file(file_id)
        if not file:
            raise FileNotFoundError(f"File {file_id} not found")

        if action == "keep":
            return file["latest_version"]

        # override: commit the loser's hashes as new version
        if not block_hashes:
            raise ValueError("block_hashes required for override")

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        version_no = file["latest_version"] + 1
        version_id = f"v_{secrets.token_hex(6)}"
        total_size = sum(len(self._object_store.get(h) or b"") for h in block_hashes)
        await self._db.insert_version(version_id, file_id, version_no,
                                      json.dumps(block_hashes), total_size, user_id, now)
        await self._db.update_file_version(file_id, version_no, total_size, "uploaded", now)

        for h in block_hashes:
            existing = await self._db.get_block(h)
            if existing:
                await self._db.increment_block_ref(h)
            else:
                data = self._object_store.get(h)
                await self._db.insert_block(h, len(data) if data else 0, now)

        await self._notifier.publish(user_id, file_id, "edit", {"action": "override"})
        return version_no

    # ─── Revisions ────────────────────────────────────────────────────

    async def list_revisions(self, file_id: str) -> list[dict]:
        versions = await self._db.get_versions_for_file(file_id)
        return [
            {"version_no": v["version_no"], "size": v["size"],
             "author_id": v["author_id"], "created_at": v["created_at"]}
            for v in versions
        ]

    # ─── Share ────────────────────────────────────────────────────────

    async def share(self, owner_id: str, file_id: str, shared_email: str, permission: str):
        file = await self._db.get_file(file_id)
        if not file:
            raise FileNotFoundError(f"File {file_id} not found")
        if file["user_id"] != owner_id:
            raise PermissionDeniedError("Only owner can share")

        target = await self._db.get_user_by_email(shared_email)
        if not target:
            raise FileNotFoundError(f"User {shared_email} not found")

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        await self._db.insert_share(file_id, owner_id, target["user_id"], permission, now)
        await self._notifier.publish(target["user_id"], file_id, "share",
                                     {"name": file["name"], "shared_by": owner_id, "permission": permission})

    # ─── List Files ───────────────────────────────────────────────────

    async def list_files(self, user_id: str) -> list[dict]:
        own = await self._db.list_files_by_user(user_id)
        shared = await self._db.list_files_shared_with(user_id)
        seen = {f["file_id"] for f in own}
        result = list(own)
        for f in shared:
            if f["file_id"] not in seen:
                result.append(f)
        return result

    # ─── GC ───────────────────────────────────────────────────────────

    async def garbage_collect(self) -> int:
        """Remove blocks with ref_count <= 0. Returns count freed."""
        zero_blocks = await self._db.get_zero_ref_blocks()
        for b in zero_blocks:
            self._object_store.delete(b["block_hash"])
            await self._db.delete_block_meta(b["block_hash"])
        return len(zero_blocks)

    # ─── Stats ────────────────────────────────────────────────────────

    async def get_stats(self) -> dict:
        users = await self._db.count_users()
        files = await self._db.count_files()
        unique_blocks = await self._db.count_blocks()
        logical_bytes = await self._db.sum_file_sizes()
        stored_bytes = self._object_store.total_stored_bytes()
        return {
            "users": users,
            "files": files,
            "unique_blocks": unique_blocks,
            "logical_bytes": logical_bytes,
            "stored_bytes": stored_bytes,
        }
