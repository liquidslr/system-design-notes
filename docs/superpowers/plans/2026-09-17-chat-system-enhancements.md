# Chat System Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add message history persistence, sidebar contacts enhancement, group-to-friend adding, and friend-to-group inviting to the existing chat system.

**Architecture:** Synchronous dual-write to PostgreSQL + Redis for message persistence. PostgreSQL as source of truth, Redis as hot cache with fallback reads. Frontend enhancements in existing Vue 3 components. New REST API endpoints for member-with-status queries and group invitations.

**Tech Stack:** Python FastAPI, SQLAlchemy (async), PostgreSQL, Redis, Vue 3, Pinia, Axios

---

## File Structure

### API Server — Modified Files
- `chat-system/api-server/app/models.py` — add `Message` model
- `chat-system/api-server/app/schemas.py` — add `GroupMemberStatusResponse`, `GroupInviteRequest`, `GroupInviteResponse`; update `MessageResponse`
- `chat-system/api-server/app/routers/channels.py` — add PostgreSQL fallback for message loading
- `chat-system/api-server/app/routers/groups.py` — add `members-with-status` endpoint, `invite` endpoint, PostgreSQL fallback for messages

### Chat Server — Modified Files
- `chat-system/chat-server/app/message_handler.py` — add PostgreSQL write in message sending, add `recover_messages_from_db` function
- `chat-system/chat-server/app/main.py` — call recovery function on startup

### Frontend — Modified Files
- `chat-system/frontend/src/stores/chat.js` — add `inviteToGroup`, `fetchMembersWithStatus` functions
- `chat-system/frontend/src/composables/useWebSocket.js` — handle `group_invite` message type
- `chat-system/frontend/src/components/ChatSidebar.vue` — sort friends by online status, add friend search filter, add invite button on groups
- `chat-system/frontend/src/components/GroupPanel.vue` — show `is_friend` badge, add "Add Friend" button per non-friend member
- `chat-system/frontend/src/views/Chat.vue` — wire up invite modal, handle new events

---

### Task 1: Add Message Model and Schemas (API Server)

**Files:**
- Modify: `chat-system/api-server/app/models.py`
- Modify: `chat-system/api-server/app/schemas.py`

- [ ] **Step 1: Add Message model to models.py**

Add import for `BigInteger` at the top of `models.py`, then add the `Message` class after the `Friendship` class:

```python
# In models.py, add BigInteger to the sqlalchemy import line:
from sqlalchemy import String, Text, Integer, BigInteger, ForeignKey, DateTime, func

# Add at the end of the file (after Friendship class):

class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sender_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    channel_type: Mapped[str] = mapped_column(String(20), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

Add a composite index after the class definition:

```python
from sqlalchemy import Index

# After the Message class:
Index("ix_messages_channel_created", Message.channel_id, Message.created_at.desc())
```

- [ ] **Step 2: Add new schemas to schemas.py**

Add these schemas at the end of `schemas.py`:

```python
# --- Group Member with Status ---
class GroupMemberStatusResponse(BaseModel):
    user_id: uuid.UUID
    username: str
    nickname: str | None
    avatar_url: str | None
    role: str
    online_status: str = "offline"
    is_friend: bool = False


# --- Group Invite ---
class GroupInviteRequest(BaseModel):
    friend_ids: list[uuid.UUID]


class GroupInviteResponse(BaseModel):
    invited_ids: list[uuid.UUID]
    message: str
```

- [ ] **Step 3: Commit**

```bash
git add chat-system/api-server/app/models.py chat-system/api-server/app/schemas.py
git commit -m 'feat: add Message model and new schemas for group features'
```

---

### Task 2: Message Persistence in Chat Server

**Files:**
- Modify: `chat-system/chat-server/app/message_handler.py`

- [ ] **Step 1: Add PostgreSQL write to handle_send_message**

Replace the entire `handle_send_message` function with the following. The key change is computing `channel_id` before routing, then writing to PostgreSQL after Redis KV store but before inbox fanout:

```python
async def handle_send_message(sender_id: str, receiver_id: str, content: str, channel_type: str):
    """Process an outgoing message."""
    r = await get_redis()
    msg_id = str(generator.generate())
    timestamp = int(time.time())

    # Compute channel_id
    if channel_type == "one_to_one":
        channel_id = "_".join(sorted([sender_id, receiver_id]))
    else:
        channel_id = receiver_id  # group_id

    message = {
        "message_id": msg_id,
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "content": content,
        "type": "text",
        "timestamp": timestamp,
        "channel_type": channel_type,
    }

    # Store message in Redis KV store
    await r.set(f"message:{msg_id}", json.dumps(message))

    # Persist to PostgreSQL (best-effort)
    try:
        async with async_session() as db:
            await db.execute(
                text(
                    "INSERT INTO messages (id, sender_id, channel_type, channel_id, content) "
                    "VALUES (:id, :sender_id, :channel_type, :channel_id, :content)"
                ),
                {
                    "id": int(msg_id),
                    "sender_id": sender_id,
                    "channel_type": channel_type,
                    "channel_id": channel_id,
                    "content": content,
                },
            )
            await db.commit()
    except Exception:
        logger.exception(f"Failed to persist message {msg_id} to PostgreSQL")

    if channel_type == "one_to_one":
        await _handle_one_to_one(r, sender_id, receiver_id, message)
    elif channel_type == "group":
        await _handle_group_message(r, sender_id, receiver_id, message)

    await r.aclose()
    return message
```

- [ ] **Step 2: Commit**

```bash
git add chat-system/chat-server/app/message_handler.py
git commit -m 'feat: persist messages to PostgreSQL on send'
```

---

### Task 3: Startup Recovery (Chat Server)

**Files:**
- Modify: `chat-system/chat-server/app/message_handler.py`
- Modify: `chat-system/chat-server/app/main.py`

- [ ] **Step 1: Add recover_messages_from_db function to message_handler.py**

Add this function after the `handle_sync` function at the end of the file:

```python
async def recover_messages_from_db():
    """Recover recent messages from PostgreSQL to Redis on startup."""
    r = await get_redis()
    try:
        async with async_session() as db:
            # Get distinct channels
            result = await db.execute(
                text("SELECT DISTINCT channel_id FROM messages")
            )
            channels = [row[0] for row in result.fetchall()]

            total = 0
            for channel_id in channels:
                # Get recent 100 messages per channel
                result = await db.execute(
                    text(
                        "SELECT id, sender_id, channel_type, channel_id, content, created_at "
                        "FROM messages WHERE channel_id = :cid "
                        "ORDER BY id DESC LIMIT 100"
                    ),
                    {"cid": channel_id},
                )
                rows = result.fetchall()

                for row in rows:
                    msg_id = str(row[0])
                    # Rebuild message dict
                    message = {
                        "message_id": msg_id,
                        "sender_id": str(row[1]),
                        "receiver_id": "",  # not stored, derived from channel
                        "content": row[4],
                        "type": "text",
                        "timestamp": int(row[3].timestamp()) if row[3] else 0,
                        "channel_type": row[2],
                    }

                    # Backfill Redis KV
                    await r.set(f"message:{msg_id}", json.dumps(message))

                    # Determine inbox key based on channel type
                    if row[2] == "one_to_one":
                        # Extract the two user IDs from channel_id
                        parts = row[3].split("_")
                        if len(parts) == 2:
                            for uid in parts:
                                await r.zadd(
                                    f"inbox:{uid}:{row[3]}",
                                    {msg_id: int(msg_id)},
                                )
                    else:
                        # Group message — add to all group members' inboxes
                        members_result = await db.execute(
                            text("SELECT user_id FROM group_members WHERE group_id = :gid"),
                            {"gid": row[3]},
                        )
                        for member_row in members_result.fetchall():
                            await r.zadd(
                                f"inbox:{str(member_row[0])}:{row[3]}",
                                {msg_id: int(msg_id)},
                            )

                total += len(rows)

            logger.info(f"Recovered {total} messages from PostgreSQL to Redis across {len(channels)} channels")
    except Exception:
        logger.exception("Failed to recover messages from PostgreSQL")
    finally:
        await r.aclose()
```

- [ ] **Step 2: Call recovery in chat server lifespan**

In `chat-server/app/main.py`, update the import and lifespan:

```python
# Update the import line:
from app.message_handler import handle_send_message, handle_sync, recover_messages_from_db

# Update the lifespan function:
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Recover messages from PostgreSQL to Redis
    await recover_messages_from_db()
    # Start Pub/Sub listener
    task = asyncio.create_task(manager.listen_pubsub())
    yield
    task.cancel()
```

- [ ] **Step 3: Commit**

```bash
git add chat-system/chat-server/app/message_handler.py chat-system/chat-server/app/main.py
git commit -m 'feat: add startup recovery of messages from PostgreSQL to Redis'
```

---

### Task 4: Message Loading with PostgreSQL Fallback (API Server)

**Files:**
- Modify: `chat-system/api-server/app/routers/channels.py`
- Modify: `chat-system/api-server/app/routers/groups.py`

- [ ] **Step 1: Add PostgreSQL fallback to channels.py**

Replace the entire `get_channel_messages` function. Add the necessary imports at the top:

```python
# Add to imports at top of channels.py:
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import Message
```

Then replace the endpoint function:

```python
@router.get("/{user_id}/messages", response_model=list[MessageResponse])
async def get_channel_messages(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    before: str | None = None,
):
    r = await get_redis()

    channel_id = "_".join(sorted([str(current_user.id), user_id]))
    inbox_key = f"inbox:{current_user.id}:{channel_id}"

    if before:
        message_ids = await r.zrangebyscore(inbox_key, "-inf", float(before) - 1, start=0, num=limit, desc=True)
    else:
        message_ids = await r.zrevrange(inbox_key, 0, limit - 1)

    messages = []
    for mid in reversed(message_ids):
        msg_data = await r.get(f"message:{mid}")
        if msg_data:
            messages.append(MessageResponse(**json.loads(msg_data)))

    await r.aclose()

    # Fallback to PostgreSQL if Redis is empty
    if not messages:
        query = select(Message).where(Message.channel_id == channel_id)
        if before:
            query = query.where(Message.id < int(before))
        query = query.order_by(Message.id.desc()).limit(limit)

        result = await db.execute(query)
        db_messages = result.scalars().all()

        for msg in reversed(db_messages):
            messages.append(MessageResponse(
                message_id=str(msg.id),
                sender_id=str(msg.sender_id),
                receiver_id=user_id,
                content=msg.content,
                type="text",
                timestamp=int(msg.created_at.timestamp()),
                channel_type=msg.channel_type,
            ))

        # Backfill Redis cache
        if db_messages:
            r = await get_redis()
            for msg in db_messages:
                msg_dict = {
                    "message_id": str(msg.id),
                    "sender_id": str(msg.sender_id),
                    "receiver_id": user_id,
                    "content": msg.content,
                    "type": "text",
                    "timestamp": int(msg.created_at.timestamp()),
                    "channel_type": msg.channel_type,
                }
                await r.set(f"message:{msg.id}", json.dumps(msg_dict))
                await r.zadd(inbox_key, {str(msg.id): msg.id})
                # Also add to peer's inbox
                peer_inbox_key = f"inbox:{user_id}:{channel_id}"
                await r.zadd(peer_inbox_key, {str(msg.id): msg.id})
            await r.aclose()

    return messages
```

- [ ] **Step 2: Add PostgreSQL fallback to groups.py message endpoint**

Add `Message` to the imports in `groups.py`:

```python
# Update the models import:
from app.models import User, Group, GroupMember, Message
```

Replace the `get_group_messages` function:

```python
@router.get("/{group_id}/messages", response_model=list[MessageResponse])
async def get_group_messages(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    before: str | None = None,
):
    gid = uuid.UUID(group_id)

    # Verify membership
    result = await db.execute(
        select(GroupMember).where(GroupMember.group_id == gid, GroupMember.user_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Not a member of this group")

    r = await get_redis()
    inbox_key = f"inbox:{current_user.id}:{group_id}"

    if before:
        message_ids = await r.zrangebyscore(inbox_key, "-inf", float(before) - 1, start=0, num=limit, desc=True)
    else:
        message_ids = await r.zrevrange(inbox_key, 0, limit - 1)

    messages = []
    for mid in reversed(message_ids):
        msg_data = await r.get(f"message:{mid}")
        if msg_data:
            messages.append(MessageResponse(**json.loads(msg_data)))

    await r.aclose()

    # Fallback to PostgreSQL if Redis is empty
    if not messages:
        query = select(Message).where(Message.channel_id == group_id)
        if before:
            query = query.where(Message.id < int(before))
        query = query.order_by(Message.id.desc()).limit(limit)

        result = await db.execute(query)
        db_messages = result.scalars().all()

        for msg in reversed(db_messages):
            messages.append(MessageResponse(
                message_id=str(msg.id),
                sender_id=str(msg.sender_id),
                receiver_id=group_id,
                content=msg.content,
                type="text",
                timestamp=int(msg.created_at.timestamp()),
                channel_type=msg.channel_type,
            ))

        # Backfill Redis cache
        if db_messages:
            r = await get_redis()
            for msg in db_messages:
                msg_dict = {
                    "message_id": str(msg.id),
                    "sender_id": str(msg.sender_id),
                    "receiver_id": group_id,
                    "content": msg.content,
                    "type": "text",
                    "timestamp": int(msg.created_at.timestamp()),
                    "channel_type": msg.channel_type,
                }
                await r.set(f"message:{msg.id}", json.dumps(msg_dict))
                await r.zadd(inbox_key, {str(msg.id): msg.id})
            await r.aclose()

    return messages
```

- [ ] **Step 3: Commit**

```bash
git add chat-system/api-server/app/routers/channels.py chat-system/api-server/app/routers/groups.py
git commit -m 'feat: add PostgreSQL fallback for message loading'
```

---

### Task 5: Members-with-Status Endpoint (API Server)

**Files:**
- Modify: `chat-system/api-server/app/routers/groups.py`

- [ ] **Step 1: Add the members-with-status endpoint**

Add new imports at the top of `groups.py`:

```python
from app.schemas import (
    GroupCreate, GroupResponse, GroupMemberAdd, GroupMemberResponse,
    MessageResponse, GroupMemberStatusResponse, GroupInviteRequest, GroupInviteResponse,
)
from app.models import User, Group, GroupMember, Message, Friendship
```

Add the new endpoint after the existing `list_members` endpoint:

```python
@router.get("/{group_id}/members-with-status", response_model=list[GroupMemberStatusResponse])
async def list_members_with_status(
    group_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get group members with online status and friendship info."""
    gid = uuid.UUID(group_id)

    # Get all members
    result = await db.execute(
        select(User, GroupMember.role)
        .join(GroupMember, User.id == GroupMember.user_id)
        .where(GroupMember.group_id == gid)
    )
    rows = result.all()

    # Get current user's friends
    friend_result = await db.execute(
        select(Friendship.friend_id).where(
            Friendship.user_id == current_user.id,
            Friendship.status == "accepted",
        )
    )
    friend_ids = set(str(fid) for fid in friend_result.scalars().all())

    # Get online statuses from Redis
    r = await get_redis()
    responses = []
    for user, role in rows:
        presence = await r.hgetall(f"presence:{user.id}")
        online_status = presence.get("status", "offline") if presence else "offline"
        responses.append(
            GroupMemberStatusResponse(
                user_id=user.id,
                username=user.username,
                nickname=user.nickname,
                avatar_url=user.avatar_url,
                role=role,
                online_status=online_status,
                is_friend=str(user.id) in friend_ids,
            )
        )

    await r.aclose()
    return responses
```

- [ ] **Step 2: Commit**

```bash
git add chat-system/api-server/app/routers/groups.py
git commit -m 'feat: add members-with-status endpoint for group panel'
```

---

### Task 6: Invite Friends to Group Endpoint (API Server)

**Files:**
- Modify: `chat-system/api-server/app/routers/groups.py`

- [ ] **Step 1: Add the invite endpoint**

Add this endpoint after the `list_members_with_status` endpoint:

```python
@router.post("/{group_id}/invite", response_model=GroupInviteResponse)
async def invite_friends_to_group(
    group_id: str,
    data: GroupInviteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Invite friends to join a group. Any member can invite."""
    gid = uuid.UUID(group_id)

    # Verify current user is a member
    result = await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == gid,
            GroupMember.user_id == current_user.id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Not a member of this group")

    # Verify each friend_id is actually a friend
    friend_result = await db.execute(
        select(Friendship.friend_id).where(
            Friendship.user_id == current_user.id,
            Friendship.status == "accepted",
        )
    )
    friend_ids = set(str(fid) for fid in friend_result.scalars().all())

    invited_ids = []
    for fid in data.friend_ids:
        fid_str = str(fid)
        if fid_str not in friend_ids:
            continue  # skip non-friends silently

        # Check if already a member
        member_result = await db.execute(
            select(GroupMember).where(
                GroupMember.group_id == gid,
                GroupMember.user_id == fid,
            )
        )
        if member_result.scalar_one_or_none():
            continue  # already a member, skip

        # Add as member
        new_member = GroupMember(group_id=gid, user_id=fid, role="member")
        db.add(new_member)
        invited_ids.append(fid_str)

    await db.commit()

    # Publish invite notifications via Redis Pub/Sub
    if invited_ids:
        r = await get_redis()
        # Fetch group name
        group_result = await db.execute(select(Group).where(Group.id == gid))
        group = group_result.scalar_one()

        for uid in invited_ids:
            payload = {
                "type": "group_invite",
                "target_user_ids": [uid],
                "group_id": str(gid),
                "group_name": group.name,
                "inviter_id": str(current_user.id),
            }
            await r.publish("chat:messages", json.dumps(payload))

        await r.aclose()

    return GroupInviteResponse(
        invited_ids=invited_ids,
        message=f"Invited {len(invited_ids)} friend(s) to group",
    )
```

- [ ] **Step 2: Commit**

```bash
git add chat-system/api-server/app/routers/groups.py
git commit -m 'feat: add invite friends to group endpoint'
```

---

### Task 7: Frontend Store and WebSocket Updates

**Files:**
- Modify: `chat-system/frontend/src/stores/chat.js`
- Modify: `chat-system/frontend/src/composables/useWebSocket.js`

- [ ] **Step 1: Add new functions to chat.js store**

Add these functions inside the store (before the `return` statement), and update the return:

```javascript
  // Add after updateOnlineStatus function:

  async function fetchMembersWithStatus(groupId) {
    const res = await axios.get(`${API_BASE}/groups/${groupId}/members-with-status`)
    return res.data
  }

  async function inviteToGroup(groupId, friendIds) {
    const res = await axios.post(`${API_BASE}/groups/${groupId}/invite`, {
      friend_ids: friendIds,
    })
    return res.data
  }

  // Update the return statement to include new functions:
  return {
    friends, groups, pendingRequests, sentRequests,
    conversations, activeChannel, onlineStatuses,
    fetchFriends, fetchGroups, fetchPendingRequests, fetchSentRequests,
    acceptRequest, rejectRequest, cancelRequest,
    loadMessages, addMessage, setActiveChannel, updateOnlineStatus,
    fetchMembersWithStatus, inviteToGroup,
  }
```

- [ ] **Step 2: Handle group_invite in useWebSocket.js**

In `useWebSocket.js`, add a new `else if` branch in the `onmessage` handler (after the `presence_update` case):

```javascript
      } else if (data.type === 'group_invite') {
        // Refresh groups list when invited to a new group
        await chatStore.fetchGroups()
      } else if (data.type === 'error') {
```

Note: the `onmessage` handler needs to be made `async`:

```javascript
    ws.value.onmessage = async (event) => {
```

- [ ] **Step 3: Commit**

```bash
git add chat-system/frontend/src/stores/chat.js chat-system/frontend/src/composables/useWebSocket.js
git commit -m 'feat: add invite and members-with-status to store, handle group_invite WS'
```

---

### Task 8: Sidebar Enhancement — Friend Sorting and Group Invite Button

**Files:**
- Modify: `chat-system/frontend/src/components/ChatSidebar.vue`

- [ ] **Step 1: Add computed sorted friends list and friend search filter**

In the `<script setup>` section, add `computed` to the import and add new computed properties:

```javascript
import { ref, computed } from 'vue'
```

Add after the existing refs:

```javascript
const friendFilter = ref('')

const sortedFriends = computed(() => {
  if (!props.friends) return []
  let list = [...props.friends]
  // Filter by friend name
  if (friendFilter.value) {
    const q = friendFilter.value.toLowerCase()
    list = list.filter(f =>
      (f.nickname || '').toLowerCase().includes(q) ||
      (f.username || '').toLowerCase().includes(q)
    )
  }
  // Sort: online first, then alphabetical
  list.sort((a, b) => {
    const aOnline = a.online_status === 'online' ? 0 : 1
    const bOnline = b.online_status === 'online' ? 0 : 1
    if (aOnline !== bOnline) return aOnline - bOnline
    const aName = (a.nickname || a.username || '').toLowerCase()
    const bName = (b.nickname || b.username || '').toLowerCase()
    return aName.localeCompare(bName)
  })
  return list
})
```

- [ ] **Step 2: Update template — friends section with filter and sorted list**

Replace the existing Friends List section (the `<div class="section">` containing the friends loop) with:

```html
    <!-- Friends List (Contacts) -->
    <div class="section">
      <h3>Contacts <span class="count-badge muted">{{ sortedFriends.length }}</span></h3>
      <div v-if="sortedFriends.length > 3" class="friend-filter">
        <input v-model="friendFilter" placeholder="Filter friends..." />
      </div>
      <div v-for="friend in sortedFriends" :key="friend.user_id" class="contact"
           :class="{ active: activeChannel?.id === friend.user_id }"
           @click="$emit('selectFriend', friend)">
        <OnlineIndicator :status="friend.online_status" />
        <span class="contact-name">{{ friend.nickname || friend.username }}</span>
        <button @click.stop="removeFriend(friend)" class="remove-btn" title="Remove">&#128465;</button>
      </div>
      <p v-if="!sortedFriends.length && !friendFilter" class="empty">No contacts yet. Search for users above.</p>
      <p v-if="sortedFriends.length && friendFilter" class="empty">No matching friends.</p>
    </div>
```

- [ ] **Step 3: Update template — groups section with invite button**

Replace the existing Groups List section with:

```html
    <!-- Groups List -->
    <div class="section">
      <h3>Groups</h3>
      <div v-for="group in groups" :key="group.id" class="contact group-item-row"
           :class="{ active: activeChannel?.id === group.id }"
           @click="$emit('selectGroup', group)">
        <span>&#x1F465; {{ group.name }}</span>
        <span class="badge">{{ group.member_count }}</span>
        <button @click.stop="$emit('inviteToGroup', group)" class="invite-btn" title="Invite friends">+</button>
      </div>
      <p v-if="!groups.length" class="empty">No groups yet.</p>
    </div>
```

- [ ] **Step 4: Add new emits and styles**

Update the `defineEmits` to include `inviteToGroup`:

```javascript
const emit = defineEmits(['selectFriend', 'selectGroup', 'startChat', 'showGroups', 'refreshRequests', 'inviteToGroup'])
```

Add these styles to the `<style scoped>` section:

```css
.friend-filter {
  padding: 0 1rem 0.25rem;
}

.friend-filter input {
  width: 100%;
  padding: 0.3rem 0.5rem;
  border: 1px solid #ddd;
  border-radius: 12px;
  outline: none;
  font-size: 0.8rem;
}

.group-item-row {
  position: relative;
}

.invite-btn {
  background: #667eea;
  color: white;
  border: none;
  border-radius: 50%;
  width: 22px;
  height: 22px;
  font-size: 0.8rem;
  cursor: pointer;
  margin-left: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.2s;
}

.group-item-row:hover .invite-btn {
  opacity: 1;
}

.invite-btn:hover {
  background: #5a67d8;
}
```

- [ ] **Step 5: Commit**

```bash
git add chat-system/frontend/src/components/ChatSidebar.vue
git commit -m 'feat: enhance sidebar with friend sorting, filter, and group invite button'
```

---

### Task 9: Group Panel — Add Friend from Members

**Files:**
- Modify: `chat-system/frontend/src/components/GroupPanel.vue`

- [ ] **Step 1: Update GroupPanel to show members with status**

Add `OnlineIndicator` import:

```javascript
import OnlineIndicator from './OnlineIndicator.vue'
```

Update the `loadMembers` function to use the new endpoint:

```javascript
async function loadMembers(groupId) {
  try {
    const res = await axios.get(`/api/groups/${groupId}/members-with-status`)
    members.value = res.data
  } catch (e) {
    console.error('Failed to load members:', e)
  }
}
```

- [ ] **Step 2: Update member list template with friend actions**

Replace the members list section in the template with:

```html
      <!-- Current Members -->
      <div class="members-list">
        <h5>Members ({{ members.length }})</h5>
        <div v-for="member in members" :key="member.user_id" class="member-item">
          <div class="member-info">
            <OnlineIndicator :status="member.online_status" />
            <span>{{ member.nickname || member.username }}</span>
            <span class="role-badge" :class="member.role">{{ member.role }}</span>
          </div>
          <button
            v-if="!member.is_friend && member.user_id !== currentUserId"
            @click="sendFriendRequest(member)"
            class="add-friend-small"
          >
            + Add
          </button>
          <span v-else-if="member.is_friend" class="friend-badge">Friend</span>
        </div>
      </div>
```

- [ ] **Step 3: Add currentUserId prop and sendFriendRequest function**

Add `currentUserId` to props:

```javascript
const props = defineProps({
  visible: Boolean,
  groups: Array,
  currentUserId: String,
})
```

Add the `sendFriendRequest` function in the script section:

```javascript
async function sendFriendRequest(member) {
  try {
    await axios.post('/api/friends/request', { friend_username: member.username })
    alert(`Friend request sent to ${member.nickname || member.username}`)
  } catch (e) {
    alert(e.response?.data?.detail || 'Failed to send friend request')
  }
}
```

- [ ] **Step 4: Add new styles**

Add these styles:

```css
.member-info {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
}

.add-friend-small {
  padding: 0.15rem 0.4rem;
  font-size: 0.7rem;
  background: #48bb78;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  white-space: nowrap;
}

.friend-badge {
  font-size: 0.7rem;
  padding: 0.15rem 0.4rem;
  background: #c6f6d5;
  color: #276749;
  border-radius: 4px;
  white-space: nowrap;
}
```

- [ ] **Step 5: Commit**

```bash
git add chat-system/frontend/src/components/GroupPanel.vue
git commit -m 'feat: add friend request button in group member list'
```

---

### Task 10: Invite Friends to Group Modal

**Files:**
- Modify: `chat-system/frontend/src/views/Chat.vue`

- [ ] **Step 1: Add invite modal state and template**

Add new refs in the script section:

```javascript
const showInviteModal = ref(false)
const inviteGroup = ref(null)
const selectedInvitees = ref([])
const friendsNotInGroup = ref([])
```

Add the invite modal template in the `<template>`, after the `GroupPanel` component:

```html
    <!-- Invite Friends Modal -->
    <div v-if="showInviteModal" class="modal-overlay" @click.self="closeInviteModal">
      <div class="modal-content">
        <h3>Invite Friends to {{ inviteGroup?.name }}</h3>
        <div v-if="friendsNotInGroup.length === 0" class="empty-modal">
          No friends to invite (all may already be members).
        </div>
        <div v-for="friend in friendsNotInGroup" :key="friend.user_id" class="invite-friend-row">
          <label>
            <input type="checkbox" :value="friend.user_id" v-model="selectedInvitees" />
            {{ friend.nickname || friend.username }}
          </label>
        </div>
        <div class="modal-actions">
          <button @click="closeInviteModal" class="cancel-btn">Cancel</button>
          <button
            @click="confirmInvite"
            :disabled="selectedInvitees.length === 0"
            class="confirm-btn"
          >
            Invite ({{ selectedInvitees.length }})
          </button>
        </div>
      </div>
    </div>
```

- [ ] **Step 2: Add invite handler functions**

Add these functions in the script section:

```javascript
async function openInviteModal(group) {
  inviteGroup.value = group
  showInviteModal.value = true
  selectedInvitees.value = []

  // Fetch current group members
  try {
    const membersRes = await axios.get(`/api/groups/${group.id}/members`)
    const memberIds = new Set(membersRes.data.map(m => m.user_id))
    // Filter friends who are not already members
    friendsNotInGroup.value = chatStore.friends.filter(f => !memberIds.has(f.user_id))
  } catch {
    friendsNotInGroup.value = chatStore.friends
  }
}

function closeInviteModal() {
  showInviteModal.value = false
  inviteGroup.value = null
  selectedInvitees.value = []
}

async function confirmInvite() {
  if (!inviteGroup.value || selectedInvitees.value.length === 0) return
  try {
    const result = await chatStore.inviteToGroup(inviteGroup.value.id, selectedInvitees.value)
    alert(result.message || 'Friends invited successfully')
    closeInviteModal()
    await chatStore.fetchGroups()
  } catch (e) {
    alert(e.response?.data?.detail || 'Failed to invite friends')
  }
}
```

- [ ] **Step 3: Wire up sidebar invite event and pass currentUserId to GroupPanel**

Update the `ChatSidebar` component usage to handle the new `inviteToGroup` event:

```html
    <ChatSidebar
      :friends="chatStore.friends"
      :groups="chatStore.groups"
      :online-statuses="chatStore.onlineStatuses"
      :active-channel="chatStore.activeChannel"
      :current-user="authStore.user"
      :pending-requests="chatStore.pendingRequests"
      :sent-requests="chatStore.sentRequests"
      @select-friend="selectFriend"
      @select-group="selectGroup"
      @start-chat="startChat"
      @show-groups="showGroupPanel = true"
      @refresh-requests="refreshAll"
      @invite-to-group="openInviteModal"
    />
```

Update the `GroupPanel` component usage to pass `currentUserId`:

```html
    <GroupPanel
      :visible="showGroupPanel"
      :groups="chatStore.groups"
      :current-user-id="currentUserId"
      @close="showGroupPanel = false"
      @select-group="selectGroup"
      @group-created="refreshGroups"
    />
```

- [ ] **Step 4: Add modal styles**

Add these styles to the `<style scoped>` section:

```css
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
}

.modal-content {
  background: white;
  border-radius: 12px;
  padding: 1.5rem;
  width: 360px;
  max-height: 70vh;
  overflow-y: auto;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
}

.modal-content h3 {
  margin: 0 0 1rem;
  font-size: 1.1rem;
  color: #333;
}

.empty-modal {
  color: #999;
  font-size: 0.9rem;
  padding: 0.5rem 0;
}

.invite-friend-row {
  padding: 0.4rem 0;
  border-bottom: 1px solid #f0f0f0;
}

.invite-friend-row label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 0.9rem;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 1rem;
}

.cancel-btn {
  padding: 0.4rem 1rem;
  background: #e2e8f0;
  color: #4a5568;
  border: none;
  border-radius: 6px;
  cursor: pointer;
}

.confirm-btn {
  padding: 0.4rem 1rem;
  background: #667eea;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
}

.confirm-btn:disabled {
  opacity: 0.5;
  cursor: default;
}
```

- [ ] **Step 5: Commit**

```bash
git add chat-system/frontend/src/views/Chat.vue
git commit -m 'feat: add invite friends to group modal'
```

---

### Task 11: Build and Verify

**Files:** No new file changes — build and smoke test.

- [ ] **Step 1: Rebuild Docker images**

```bash
cd chat-system
docker compose build api-server chat-server frontend
```

- [ ] **Step 2: Start services**

```bash
docker compose up -d
```

- [ ] **Step 3: Verify message persistence**

1. Register two users and send a few messages between them
2. Restart Redis: `docker compose restart redis`
3. Reload the chat page — messages should still be visible (loaded from PostgreSQL fallback)

- [ ] **Step 4: Verify sidebar enhancements**

1. Check that friends are sorted with online users first
2. Type in the friend filter — list should narrow down
3. Check that group entries show member count and invite button on hover

- [ ] **Step 5: Verify group add friend**

1. Open a group's manage panel
2. Non-friend members should show "+ Add" button
3. Click it — friend request should be sent

- [ ] **Step 6: Verify invite friends to group**

1. Hover over a group in sidebar — click the invite (+) button
2. Modal opens with friends not in the group
3. Select friends and click "Invite"
4. Invited users should appear as new group members

- [ ] **Step 7: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m 'fix: post-verification fixes for chat system enhancements'
```
