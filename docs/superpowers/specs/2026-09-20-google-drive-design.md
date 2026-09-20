# Google Drive (Cloud File Storage & Sync) — Implementation Spec

## Goal
Implement a runnable Google Drive–style cloud file storage and synchronization system based on the design in `15. Google Drive/Readme.md`. Each core concept from the chapter — 4 MB content-addressed blocks, block-level de-duplication, delta sync, resumable upload, file revision history, optimistic-concurrency sync conflict resolution, sharing with permissions, and a long-polling notification service with an offline backup queue — is realized as working code. Deployment-level concerns (real S3, multi-server sharding, cross-region replication, master/slave failover) are represented by clean module boundaries and comments rather than actual distributed infrastructure.

## Scope Decision
- **Range:** core logic complete, single-machine simulation. One FastAPI process + SQLite metadata DB + a local directory acting as the "cloud object store". No Docker, no web frontend.
- **Interaction:** a `drive-cli` client script (Python) for real end-to-end use, plus a scripted `--demo` storyline and pytest unit tests. Matches the repo convention of verification scripts used by sibling subprojects.
- **Architecture:** Approach A — a single process with an internal split between a "block server" (content-addressed block storage engine, simulating S3) and an "API server" (metadata, auth, versions, sharing, notifications), mirroring the role separation drawn in the chapter's high-level design diagram.

## Architecture

### Directory Structure
```
google-drive/
├── app/
│   ├── __init__.py
│   ├── config.py          # DriveConfig dataclass (block size, quota, port, etc.)
│   ├── models.py          # Pydantic request/response models
│   ├── database.py        # aiosqlite async metadata DB layer
│   ├── object_store.py    # Local "S3-like" blob store abstraction: data/blocks/{hash}
│   ├── block_server.py    # Content-addressed block engine: put/get/dedup/refcount (simulated block server)
│   ├── auth.py            # User register/login, token issue & verification
│   ├── api_service.py     # Core business: upload/sync/version/share/conflict/quota logic
│   ├── notification.py    # Pub/sub notification center: long polling + offline backup queue
│   └── server.py          # FastAPI app + REST API routes wiring everything
├── cli.py                 # drive-cli client (login/upload/download/sync/share/revisions/notifications/gc)
├── tests/
│   ├── conftest.py
│   └── test_*.py          # pytest units (dedup, resume, delta, conflict, notify, share, quota)
├── __main__.py            # python -m google_drive {--server|--demo|--cli ...}
├── requirements.txt
└── README.md
```
> Note: package directory is `google-drive/`; the importable module name (used by `python -m`) is `google_drive`. A thin `google_drive` alias via `__main__.py` follows the sibling `notification-system` / `news-feed-system` layout where the on-disk folder is hyphenated and the demo/entry uses `sys.path` insertion.

### Component Responsibilities & Boundaries
- **object_store.py** — lowest layer. A content-addressed key→bytes store on the local filesystem (`data/blocks/{hash}`). Existence check, write-if-absent, read, delete. Simulates S3's durability; comments note where cross-region replication / cold storage (Glacier) would live.
- **block_server.py** — the "block server" role. Splits bytes into ≤4 MB blocks, computes SHA-256 per block, delegates storage to `object_store`, maintains the `blocks` metadata table (ref_count). Provides `which_hashes_missing(hashes)` used by both de-dup and delta sync. Has no notion of users/files — pure block mechanics.
- **auth.py** — register/login; store salted hash; issue opaque session tokens verified via dependency in `server.py`.
- **api_service.py** — the "API server" business role. Owns files, versions, upload sessions, shares, quota. Orchestrates block_server for content and database for metadata. Enforces optimistic concurrency for sync conflicts.
- **notification.py** — pub/sub with `asyncio.Event`-based long polling and a persisted offline queue (`notifications` table, `delivered` flag).
- **server.py** — thin FastAPI routers over api_service / auth / notification. No business logic here.

Each module is understandable and testable through its own interface; `block_server` depends only on `object_store`+`database`; `api_service` depends on `block_server`+`database`+`notification`.

## Data Model (SQLite metadata DB)

Maps to the chapter's `metadata-database.png` (User / File / Block / File Version tables) plus tables needed for resumable upload, sharing, and notifications.

| Table | Key fields | Purpose |
|-------|-----------|---------|
| `users` | user_id (PK), email UNIQUE, pwd_hash, salt, quota_bytes (default 10 GB), used_bytes, created_at | Profile + quota accounting |
| `files` | file_id (PK), user_id, name, path, namespace, latest_version, size, storage_class, status, created_at, updated_at | Logical file entry; unique by (namespace, path); namespace = user scope echoing the chapter's namespace model |
| `blocks` | block_hash (PK), size, ref_count, created_at | Content-addressed block registry; ref_count powers de-dup + GC |
| `file_versions` | version_id (PK), file_id, version_no, block_hashes (JSON array, ordered), size, created_at, author_id | Revision history; a version = an ordered list of block hashes |
| `upload_sessions` | session_id (PK), file_id, uploader_id, total_block_count, received_hashes (JSON), state (pending/uploading/committed), created_at, updated_at | Resumable upload state machine |
| `shares` | file_id, owner_id, shared_with, permission (view/edit), created_at; PK(file_id, shared_with) | Sharing + permission |
| `notifications` | notif_id (PK), user_id, file_id, event (add/edit/delete/share), payload (JSON), delivered (0/1), created_at | Notification log doubling as offline backup queue |

- **De-duplication** happens at the `blocks` layer: `block_hash` is the PK, so identical content across files/users is stored once and `ref_count` increments.
- **Revision history**: every commit writes a `file_versions` row; `files.latest_version` points to current. List/rollback read this table.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/register` | POST | Create user (email, password) |
| `/api/login` | POST | Returns session token |
| `/api/files/list` | GET | List files in caller's namespace (+ optionally shared-in files) |
| `/api/files/upload` | POST | Start resumable upload (`?uploadType=resumable`); returns `session_id` + already-known (dedup) block hashes |
| `/api/blocks` | POST | Upload a batch of block hashes+data for a session; server stores only missing blocks (dedup/delta); returns received set |
| `/api/sessions/{session_id}` | GET | Query upload status (received vs. missing blocks) — enables resume after interruption |
| `/api/files/{file_id}/commit` | POST | Commit session → write new file_version, update files, enforce quota, emit notification |
| `/api/files/{file_id}/download` | GET | Reassemble ordered blocks of a version and return bytes (`?version=` optional) |
| `/api/files/{file_id}/revisions` | GET | List revision history |
| `/api/files/{file_id}/share` | POST | Share file with a user (view/edit) |
| `/api/sync` | POST | Client uploads its `{file_id → (base_version, block_hashes)}` state; server returns delta updates and/or 409 conflicts |
| `/api/files/{file_id}/resolve` | POST | Resolve a conflict: `override` (take my copy as new version) or `keep` (accept server version) |
| `/api/notifications` | GET | Long-poll for new events (`?wait=<sec>&since=<notif_id>`); marks delivered |
| `/api/admin/gc` | POST | Garbage-collect blocks with `ref_count == 0` (demonstrates storage optimization) |
| `/api/stats` | GET | Counts: users, files, unique blocks, bytes stored vs. logical bytes (shows dedup savings) |

## Core Flows

### Upload (Resumable + De-dup + Delta)
1. `POST /files/upload?uploadType=resumable` → create `upload_session` (state=pending); return `session_id` plus the subset of the client's declared block hashes the server already has (`deduplicated`).
2. Client chunks file into ≤4 MB blocks, computes SHA-256 per block, sends the hash manifest. Client `POST /blocks` only for hashes the server is missing — already-present blocks are never re-uploaded (**de-dup + bandwidth efficiency**).
3. Interrupted? Client `GET /sessions/{id}` to see `received` vs `missing`, then continues uploading only the missing blocks (**resumable**).
4. When all blocks are present, `POST /files/{id}/commit`: verify quota (`used_bytes + new_unique_bytes <= quota_bytes`, reject with 413 if over), write `file_versions` row, set `files.latest_version` & `status=uploaded`, bump `ref_count` on newly stored blocks, emit an `add`/`edit` notification to relevant users.

### Download
`GET /files/{id}/download` reads the ordered `block_hashes` of the requested (or latest) version, fetches each block from `block_server`/`object_store`, concatenates, and streams back. Access requires ownership or a `view` share.

### Sync & Conflict Resolution (Optimistic Concurrency)
- `POST /sync` with client state `{file_id → (base_version, block_hashes)}`:
  - **Behind:** server's `latest_version` is newer → return the file's current version metadata + the missing/changed block list so the client downloads only differing blocks (**delta sync**).
  - **Conflict:** client's proposed change is based on `base_version != latest_version` (someone else committed first) → respond `409 conflict`. The **first-processed version wins**; the losing client's blocks are retained as a separate pending version so **both copies are preserved** for user resolution (echoing the chapter's user1-wins / user2-conflict example).
- `POST /files/{id}/resolve` with `override` (promote the loser's copy to a new version) or `keep` (discard local, adopt server).

### Notification (Long Polling + Offline Queue)
- Write operations insert a `notifications` row (`delivered=0`) and signal an in-process `asyncio.Event`.
- `GET /notifications?wait=30&since=<id>`: if undelivered events exist beyond `since`, return immediately; otherwise await the event up to `wait` seconds, then return (empty on timeout). Returned rows are marked `delivered=1`.
- Offline clients simply call again with their last-seen `since` id after reconnecting and pull everything they missed (**offline backup queue**).

### Sharing & Permissions
- `POST /files/{id}/share` records a `view` or `edit` grant. Download requires `view`; commit/sync edits require ownership or `edit`. Sharing emits a `share` notification to the grantee.

## Configuration (`config.py`, `DriveConfig` dataclass)
- `block_size = 4 * 1024 * 1024` (4 MB, per chapter)
- `default_quota_bytes = 10 * 1024**3` (10 GB)
- `max_file_size_bytes = 10 * 1024**3`
- `max_versions_kept` (revision cap; simplest policy — keep all, note the chapter's "limit revisions" idea in comments)
- `data_dir`, `blocks_dir = data/blocks`, `db_path`
- `host`, `port` (pick an unused port consistent with siblings, e.g. 9200)
- `long_poll_timeout_sec`

## Error Handling
- Over quota → `413`. Unauthorized download/edit → `403`. Unknown file/session/block-hash mismatch → `404` / `400`. Commit before all blocks received → `409` with missing count. Conflict → `409` with both version descriptors. Content integrity: block upload verifies SHA-256 matches its hash; mismatch → `400`.
- Conceptual failures from the chapter (load-balancer, block-server, metadata-DB, cloud-storage, notification-service outages) are documented in `README.md` as "what a real deployment does"; in-process we only emulate notification reconnect + offline pull and block GC.

## Storage Optimization
- De-dup (blocks PK + ref_count) — measurable via `/api/stats` (logical bytes vs. physical stored bytes).
- GC endpoint removes `ref_count == 0` blocks (demonstrates reclaiming space after deletions/version caps).
- `storage_class` column on `files` (`hot`/`cold`) marks the cold-storage concept without a separate tier (comment explains Glacier analogue).

## Out of Scope (YAGNI)
Real distributed sharding, multi-process/container deployment, actual Amazon S3, cross-region replication, compression/encryption pipelines (interface stubs + comments only), web UI, incremental (rsync-style) block differencing beyond whole-block delta.

## Tech Stack
- Python 3.11, FastAPI, uvicorn, aiosqlite (async SQLite), Pydantic v2, `hashlib` (SHA-256), pytest + httpx/asyncio for tests.

## Testing
- **pytest units** (`tests/`): dedup hit (same content twice → one block, ref_count 2); resumable (partial upload → status reports missing → resume completes); delta (edit one block of a multi-block file → only that block uploaded on commit); conflict (two clients off same base → second gets 409, both versions retained, override works); notification long-poll (event wakes waiter); share permission (view can download, cannot edit → 403); quota (upload beyond 10 GB logical unique bytes → 413).
- **`--demo`** storyline: register two users, upload a multi-block file, show dedup by re-uploading identical content, download & verify, simulate two devices editing the same file → conflict → resolve, share a file and show long-poll notification delivery, print `/api/stats` dedup savings.

## Data Flow Summary
1. Client chunks file → hashes → server stores only missing blocks (dedup/delta) → commit writes an ordered-hash version + enforces quota.
2. Sync compares client base_version vs. server latest → sends deltas or raises a conflict; conflicts keep both copies for user resolution.
3. Every mutation logs a notification; online clients are woken via long polling, offline clients pull on reconnect.
4. Sharing grants view/edit access enforced on download/commit; blocks with no references are reclaimable via GC.
