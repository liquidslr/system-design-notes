# Chat System Enhancements Design

## Overview

Add four feature areas to the existing chat system: enhanced sidebar contacts, friend-adding from groups, inviting friends to groups, and message history persistence to PostgreSQL.

## Current State

The chat system consists of five microservices (API Server, Chat Server, Presence Server, Notification Server, Frontend) backed by PostgreSQL and Redis. Key observations:

- **Friends**: Full friend request lifecycle exists (send, accept, reject, cancel, remove, list with online status)
- **Messages**: Ephemeral — stored only in Redis (KV store + sorted sets). Redis restart loses all messages
- **Sidebar**: Shows friends list, pending requests, and groups — no grouping, sorting, or invite features
- **Groups**: Support up to 100 members with admin-managed member addition. No invite mechanism

## Design Decisions

### Message Persistence: Synchronous Dual-Write (Approach A)

Chosen over async batch write (Approach B) and PostgreSQL-only (Approach C) for simplicity and reliability.

## Feature 1: Message History Persistence

### Data Model

New `messages` table in PostgreSQL:

| Column | Type | Description |
|--------|------|-------------|
| id | BigInteger (PK) | Snowflake ID, consistent with existing message IDs |
| sender_id | UUID (FK → users.id) | Message sender |
| channel_type | String | `one_to_one` or `group` |
| channel_id | String | Sorted user ID pair for 1-on-1, group_id for groups |
| content | Text | Message body |
| created_at | DateTime (UTC) | Message creation timestamp |

Indexes:
- `(channel_id, created_at DESC)` — composite index for paginated channel queries
- `(sender_id)` — for user message lookups

### Write Path (Chat Server)

Message sending flow becomes:

1. Generate Snowflake ID (existing)
2. **Write to PostgreSQL `messages` table** (new)
3. Write to Redis KV `message:{id}` (existing)
4. Add to Redis inbox sorted sets `inbox:{user_id}:{channel_id}` (existing)
5. Publish to Redis Pub/Sub global channel (existing)

Steps 2-5 execute sequentially. If PostgreSQL write fails, log the error and continue with steps 3-5 (best-effort persistence — message may be lost if Redis also fails).

### Read Path (API Server)

Message loading flow:

1. Query Redis inbox sorted set for the channel (existing)
2. If Redis returns data → return messages (fast path, no change)
3. If Redis returns empty → query PostgreSQL with pagination, backfill Redis cache, return results

This ensures messages survive Redis restarts without changing the happy-path performance.

### Startup Recovery (Chat Server)

On Chat Server startup:
- Query all channels that have messages in PostgreSQL (distinct channel_id)
- For each channel, load the most recent 100 messages
- Backfill Redis KV and inbox sorted sets
- Ensures cache is warm immediately after restart

### API Changes

No new API endpoints needed. Existing endpoints modified:

- `GET /api/channels/{user_id}/messages` — add PostgreSQL fallback
- `GET /api/groups/{group_id}/messages` — add PostgreSQL fallback

Both endpoints add optional query params: `limit` (default 50, max 200) and `before` (message ID cursor — messages with ID less than this value are returned, enabling backward pagination through history).

## Feature 2: Sidebar Contacts Enhancement

### Frontend Changes to `ChatSidebar.vue`

**Friend List Improvements:**
- Sort friends by online status: online friends first, offline friends below
- Add online status indicator (green/gray dot) next to each friend name
- Search box filters friends by nickname/username in real-time

**Group Panel Improvements:**
- Show member count next to each group name (e.g., "群组A (5人)")
- Add "Invite" button on each group entry for inviting friends to the group

**Sidebar Layout:**

```
┌─────────────────────┐
│ 🔍 Search box       │
├─────────────────────┤
│ 👥 Friends          │
│  ● Friend A (online)│
│  ● Friend B (online)│
│  ○ Friend C (offline)│
├─────────────────────┤
│ 📋 Pending (N)      │
├─────────────────────┤
│ 🏠 Groups           │
│  Group A (5) [Invite]│
│  Group B (3) [Invite]│
└─────────────────────┘
```

### Backend Changes

New endpoint: `GET /api/groups/{group_id}/members-with-status`

Returns group members with:
- User details (id, username, nickname, avatar_url)
- Online status from Redis presence
- `is_friend` boolean — whether this member is a friend of the current user
- `role` — admin or member

This supports both the group panel display and the "add friend from group" feature.

## Feature 3: Add Friend from Group

### Frontend Interaction

1. User opens a group → `GroupPanel.vue` shows member list
2. Each non-friend member has an "Add Friend" button
3. Clicking the button calls `POST /api/friends/request` with the member's username
4. Already-friend members show a "Friends" badge, button disabled

### Backend Changes

Modify existing `GET /api/groups/{group_id}/members` (or use the new `members-with-status` endpoint):
- Add `is_friend` field to each member response
- Frontend uses this to conditionally show "Add Friend" button or "Friends" badge

No new API endpoints needed — reuses existing friend request endpoint.

## Feature 4: Invite Friends to Group

### Frontend Interaction

1. User clicks "Invite" button on a group in the sidebar
2. Modal opens showing the user's friend list, excluding members already in the group
3. User selects friends to invite (checkboxes)
4. Clicks "Confirm" → calls `POST /api/groups/{group_id}/invite`
5. Invited friends are immediately added as group members

### Backend: New API

`POST /api/groups/{group_id}/invite`

Request body:
```json
{
  "friend_ids": ["uuid1", "uuid2"]
}
```

Behavior:
- Validates current user is a member of the group
- Validates each friend_id is actually a friend of the current user
- Creates `GroupMember` records for each invited friend (role = "member")
- Skips users who are already members (idempotent)
- Returns list of successfully invited users

### Notification

Invited users receive a WebSocket notification (via existing Pub/Sub mechanism) informing them they've been added to a group. The notification message type is `group_invite` and includes `group_id`, `group_name`, and `inviter_id`. The frontend handles this by refreshing the groups list via `fetchGroups()`.

## Files to Modify

### API Server
- `app/models.py` — add `Message` model
- `app/schemas.py` — add message-related schemas, update member response with `is_friend`
- `app/routers/channels.py` — add PostgreSQL fallback for message loading
- `app/routers/groups.py` — add `members-with-status` endpoint, `invite` endpoint, PostgreSQL fallback for messages
- `app/database.py` — no changes needed (existing async setup works)

### Chat Server
- `app/message_handler.py` — add PostgreSQL write in message sending flow
- `app/main.py` — add startup recovery logic (backfill Redis from PostgreSQL)
- `app/config.py` — no changes needed (DATABASE_URL already configured)

### Frontend
- `src/components/ChatSidebar.vue` — friend sorting, online indicators, group invite button
- `src/components/GroupPanel.vue` — add friend button per member, online status
- `src/stores/chat.js` — add invite function, member-with-status fetching
- `src/views/Chat.vue` — wire up invite modal

### Database Migration
- New `messages` table created via SQLAlchemy `create_all()` on startup (consistent with existing pattern)

## Error Handling

- **PostgreSQL write failure**: Log error, continue with Redis delivery (message may be lost if Redis also fails)
- **Redis cache miss**: Transparently fall back to PostgreSQL, backfill Redis
- **Invite non-friend**: Return 400 error with clear message
- **Duplicate invite**: Idempotent — skip already-members silently

## Testing Strategy

- Verify message persistence: send message → restart Redis → confirm messages still loadable
- Verify sidebar: friends sorted by online status, search filters correctly
- Verify group add friend: send request from group panel → friend request appears for target user
- Verify invite: invite friends → they appear as group members → receive notification
