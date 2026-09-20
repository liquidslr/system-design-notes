"""Pydantic request/response models for the Google Drive API."""
from __future__ import annotations
from pydantic import BaseModel


# --- Auth ---

class RegisterRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    token: str
    user_id: str


# --- Upload ---

class UploadStartRequest(BaseModel):
    file_name: str
    path: str
    size: int
    total_block_count: int
    file_id: str | None = None       # for edits (new version of existing file)
    base_version: int | None = None   # client's current version for conflict detection
    block_hashes: list[str] | None = None  # manifest for dedup pre-check


class UploadStartResponse(BaseModel):
    session_id: str
    file_id: str
    deduplicated_hashes: list[str]    # hashes server already has


class BlockItem(BaseModel):
    hash: str
    data_b64: str                     # base64-encoded raw block


class BlockUploadRequest(BaseModel):
    session_id: str
    blocks: list[BlockItem]


class BlockUploadResponse(BaseModel):
    received_hashes: list[str]


class SessionStatusResponse(BaseModel):
    session_id: str
    received_hashes: list[str]
    missing_count: int
    state: str


class CommitRequest(BaseModel):
    session_id: str
    block_hashes: list[str]


class CommitResponse(BaseModel):
    file_id: str
    version_no: int


# --- Download ---

class FileInfo(BaseModel):
    file_id: str
    name: str
    path: str
    size: int
    latest_version: int
    status: str
    updated_at: str


# --- Revisions ---

class RevisionItem(BaseModel):
    version_no: int
    size: int
    author_id: str
    created_at: str


# --- Sync ---

class FileSyncState(BaseModel):
    file_id: str
    base_version: int
    block_hashes: list[str]


class SyncRequest(BaseModel):
    states: list[FileSyncState]


class SyncUpdate(BaseModel):
    file_id: str
    server_version: int
    block_hashes: list[str]
    size: int


class SyncConflict(BaseModel):
    file_id: str
    client_base_version: int
    server_version: int
    server_block_hashes: list[str]


class SyncResponse(BaseModel):
    updates: list[SyncUpdate] = []
    conflicts: list[SyncConflict] = []


# --- Resolve ---

class ResolveRequest(BaseModel):
    action: str  # "override" or "keep"
    block_hashes: list[str] | None = None


class ResolveResponse(BaseModel):
    file_id: str
    new_version_no: int


# --- Share ---

class ShareRequest(BaseModel):
    shared_with: str  # email of target user
    permission: str = "view"  # view | edit


# --- Notification ---

class NotificationItem(BaseModel):
    notif_id: int
    file_id: str
    event: str
    payload: dict = {}
    created_at: str


# --- Stats ---

class StatsResponse(BaseModel):
    users: int
    files: int
    unique_blocks: int
    logical_bytes: int
    stored_bytes: int
