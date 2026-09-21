<template>
  <div class="sidebar">
    <div class="sidebar-header">
      <div class="user-info">
        <h2>{{ currentUser?.nickname || currentUser?.username || 'Chats' }}</h2>
      </div>
      <div class="header-actions">
        <button @click="$emit('showGroups')" class="icon-btn" title="Groups">&#x1F465;</button>
        <button @click="$router.push('/profile')" class="icon-btn" title="Profile">&#x1F464;</button>
      </div>
    </div>

    <div class="search-box">
      <input v-model="searchQuery" placeholder="Search users..." @input="searchUsers" />
    </div>

    <!-- Search Results -->
    <div v-if="searchResults.length" class="section">
      <h3>Search Results</h3>
      <div v-for="user in searchResults" :key="user.id" class="contact">
        <OnlineIndicator :status="onlineStatuses[user.id] || 'offline'" />
        <span class="contact-name" @click="$emit('startChat', user)">{{ user.nickname || user.username }}</span>
        <button
          v-if="!isFriend(user.id) && !isSent(user.id)"
          @click.stop="addFriend(user)"
          :disabled="friendStatuses[user.id] === 'sent'"
          class="add-friend-btn"
        >
          {{ friendStatuses[user.id] === 'sent' ? 'Sent' : '+ Add' }}
        </button>
        <span v-else-if="isSent(user.id)" class="status-tag pending">Pending</span>
        <span v-else class="status-tag friend">Friend</span>
      </div>
    </div>

    <!-- Pending Friend Requests (Incoming) -->
    <div class="section" v-if="pendingRequests.length">
      <h3>Friend Requests <span class="count-badge">{{ pendingRequests.length }}</span></h3>
      <div v-for="req in pendingRequests" :key="req.user_id" class="contact request-item">
        <div class="request-info" @click="$emit('startChat', { id: req.user_id, nickname: req.nickname, username: req.username })">
          <span>{{ req.nickname || req.username }}</span>
        </div>
        <div class="request-actions">
          <button @click.stop="acceptReq(req.user_id)" class="accept-btn" title="Accept">&#10003;</button>
          <button @click.stop="rejectReq(req.user_id)" class="reject-btn" title="Reject">&#10007;</button>
        </div>
      </div>
    </div>

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
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import axios from 'axios'
import OnlineIndicator from './OnlineIndicator.vue'

const props = defineProps({
  friends: Array,
  groups: Array,
  onlineStatuses: Object,
  activeChannel: Object,
  currentUser: Object,
  pendingRequests: Array,
  sentRequests: Array,
})

const emit = defineEmits(['selectFriend', 'selectGroup', 'startChat', 'showGroups', 'refreshRequests', 'inviteToGroup'])

const searchQuery = ref('')
const searchResults = ref([])
const friendStatuses = ref({})
const friendFilter = ref('')

const sortedFriends = computed(() => {
  if (!props.friends) return []
  let list = [...props.friends]
  if (friendFilter.value) {
    const q = friendFilter.value.toLowerCase()
    list = list.filter(f =>
      (f.nickname || '').toLowerCase().includes(q) ||
      (f.username || '').toLowerCase().includes(q)
    )
  }
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

function isFriend(userId) {
  return props.friends.some(f => f.user_id === userId)
}

function isSent(userId) {
  return props.sentRequests.some(r => r.user_id === userId)
}

async function searchUsers() {
  if (searchQuery.value.length < 1) {
    searchResults.value = []
    return
  }
  try {
    const res = await axios.get(`/api/users/search?q=${searchQuery.value}`)
    searchResults.value = res.data
  } catch {
    searchResults.value = []
  }
}

async function addFriend(user) {
  try {
    await axios.post('/api/friends/request', { friend_username: user.username })
    friendStatuses.value[user.id] = 'sent'
    emit('refreshRequests')
  } catch (e) {
    alert(e.response?.data?.detail || 'Failed to send friend request')
  }
}

async function acceptReq(userId) {
  try {
    await axios.put(`/api/friends/${userId}/accept`)
    emit('refreshRequests')
  } catch (e) {
    alert(e.response?.data?.detail || 'Failed to accept request')
  }
}

async function rejectReq(userId) {
  try {
    await axios.put(`/api/friends/${userId}/reject`)
    emit('refreshRequests')
  } catch (e) {
    alert(e.response?.data?.detail || 'Failed to reject request')
  }
}

async function removeFriend(friend) {
  if (!confirm(`Remove ${friend.nickname || friend.username} from contacts?`)) return
  try {
    await axios.delete(`/api/friends/${friend.user_id}`)
    emit('refreshRequests')
  } catch (e) {
    alert(e.response?.data?.detail || 'Failed to remove friend')
  }
}
</script>

<style scoped>
.sidebar {
  width: 300px;
  background: white;
  border-right: 1px solid #e0e0e0;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow-y: auto;
}

.sidebar-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem;
  border-bottom: 1px solid #eee;
}

.user-info h2 { font-size: 1.1rem; color: #333; margin: 0; }

.header-actions {
  display: flex;
  gap: 4px;
}

.icon-btn {
  background: none;
  border: none;
  font-size: 1.2rem;
  cursor: pointer;
}

.search-box {
  padding: 0.5rem 1rem;
}

.search-box input {
  width: 100%;
  padding: 0.5rem;
  border: 1px solid #ddd;
  border-radius: 20px;
  outline: none;
  font-size: 0.9rem;
}

.section {
  padding: 0.5rem 0;
}

.section h3 {
  padding: 0.25rem 1rem;
  font-size: 0.8rem;
  color: #999;
  text-transform: uppercase;
  display: flex;
  align-items: center;
  gap: 6px;
}

.count-badge {
  background: #e53e3e;
  color: white;
  font-size: 0.65rem;
  padding: 1px 6px;
  border-radius: 8px;
  text-transform: none;
}

.count-badge.muted {
  background: #a0aec0;
}

.contact {
  display: flex;
  align-items: center;
  padding: 0.6rem 1rem;
  cursor: pointer;
  transition: background 0.2s;
}

.contact:hover, .contact.active {
  background: #f0f2f5;
}

.contact-name {
  flex: 1;
}

.request-item {
  padding: 0.5rem 1rem;
}

.request-info {
  flex: 1;
  cursor: pointer;
}

.request-actions {
  display: flex;
  gap: 4px;
}

.accept-btn {
  background: #48bb78;
  color: white;
  border: none;
  border-radius: 50%;
  width: 28px;
  height: 28px;
  font-size: 0.9rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.reject-btn {
  background: #fc8181;
  color: white;
  border: none;
  border-radius: 50%;
  width: 28px;
  height: 28px;
  font-size: 0.9rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.remove-btn {
  background: none;
  border: none;
  color: #a0aec0;
  font-size: 0.85rem;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.2s;
  padding: 2px 4px;
}

.contact:hover .remove-btn {
  opacity: 1;
}

.remove-btn:hover {
  color: #e53e3e;
}

.add-friend-btn {
  margin-left: auto;
  padding: 0.2rem 0.5rem;
  font-size: 0.75rem;
  background: #48bb78;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  white-space: nowrap;
}

.add-friend-btn:disabled {
  background: #a0aec0;
  cursor: default;
}

.status-tag {
  margin-left: auto;
  font-size: 0.7rem;
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
}

.status-tag.pending {
  background: #fefcbf;
  color: #975a16;
}

.status-tag.friend {
  background: #c6f6d5;
  color: #276749;
}

.empty {
  padding: 0.5rem 1rem;
  color: #999;
  font-size: 0.85rem;
}

.badge {
  margin-left: auto;
  background: #667eea;
  color: white;
  border-radius: 10px;
  padding: 2px 8px;
  font-size: 0.75rem;
}

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
</style>
