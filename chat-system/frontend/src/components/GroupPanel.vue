<template>
  <div class="group-panel" v-if="visible">
    <div class="panel-header">
      <h3>Groups</h3>
      <button @click="$emit('close')" class="close-btn">&times;</button>
    </div>

    <!-- Create Group -->
    <div class="section">
      <h4>Create Group</h4>
      <input v-model="newGroupName" placeholder="Group name" />
      <input v-model="newGroupDesc" placeholder="Description (optional)" />
      <button @click="createGroup" :disabled="!newGroupName.trim()">Create</button>
    </div>

    <!-- My Groups -->
    <div class="section">
      <h4>My Groups</h4>
      <div v-for="group in groups" :key="group.id" class="group-item">
        <div>
          <strong>{{ group.name }}</strong>
          <p>{{ group.member_count }} members</p>
        </div>
        <div class="group-actions">
          <button @click="$emit('selectGroup', group)">Open</button>
          <button @click="openManage(group)" class="manage-btn">Manage</button>
        </div>
      </div>
    </div>

    <!-- Manage Group Members -->
    <div class="section" v-if="managingGroup">
      <h4>Manage: {{ managingGroup.name }}</h4>

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

      <!-- Add Member -->
      <div class="add-member">
        <h5>Add Member</h5>
        <input
          v-model="searchQuery"
          placeholder="Search user..."
          @input="onSearchInput"
        />
        <div v-if="searchResults.length" class="search-results">
          <div
            v-for="user in searchResults"
            :key="user.id"
            class="search-result-item"
          >
            <span>{{ user.nickname || user.username }}</span>
            <button
              @click="addMember(user)"
              :disabled="isAlreadyMember(user.id)"
            >
              {{ isAlreadyMember(user.id) ? 'Already member' : 'Add' }}
            </button>
          </div>
        </div>
        <p v-if="searchError" class="error-msg">{{ searchError }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import axios from 'axios'
import OnlineIndicator from './OnlineIndicator.vue'

const props = defineProps({
  visible: Boolean,
  groups: Array,
  currentUserId: String,
})

const emit = defineEmits(['close', 'selectGroup', 'groupCreated'])

const newGroupName = ref('')
const newGroupDesc = ref('')

// Member management state
const managingGroup = ref(null)
const members = ref([])
const searchQuery = ref('')
const searchResults = ref([])
const searchError = ref('')
let searchTimeout = null

async function createGroup() {
  if (!newGroupName.value.trim()) return
  try {
    await axios.post('/api/groups', {
      name: newGroupName.value,
      description: newGroupDesc.value || null,
    })
    newGroupName.value = ''
    newGroupDesc.value = ''
    emit('groupCreated')
  } catch (e) {
    alert(e.response?.data?.detail || 'Failed to create group')
  }
}

function openManage(group) {
  managingGroup.value = group
  searchQuery.value = ''
  searchResults.value = []
  searchError.value = ''
  loadMembers(group.id)
}

async function loadMembers(groupId) {
  try {
    const res = await axios.get(`/api/groups/${groupId}/members-with-status`)
    members.value = res.data
  } catch (e) {
    console.error('Failed to load members:', e)
  }
}

async function sendFriendRequest(member) {
  try {
    await axios.post('/api/friends/request', { friend_username: member.username })
    alert(`Friend request sent to ${member.nickname || member.username}`)
  } catch (e) {
    alert(e.response?.data?.detail || 'Failed to send friend request')
  }
}

function onSearchInput() {
  clearTimeout(searchTimeout)
  if (!searchQuery.value.trim()) {
    searchResults.value = []
    return
  }
  searchTimeout = setTimeout(doSearch, 300)
}

async function doSearch() {
  if (!searchQuery.value.trim()) return
  try {
    const res = await axios.get(`/api/users/search?q=${encodeURIComponent(searchQuery.value)}`)
    searchResults.value = res.data
    searchError.value = ''
  } catch (e) {
    searchError.value = 'Search failed'
    searchResults.value = []
  }
}

function isAlreadyMember(userId) {
  return members.value.some(m => m.user_id === userId)
}

async function addMember(user) {
  if (!managingGroup.value) return
  try {
    await axios.post(`/api/groups/${managingGroup.value.id}/members`, {
      user_id: user.id,
    })
    // Refresh members list
    await loadMembers(managingGroup.value.id)
    // Refresh groups list to update member count
    emit('groupCreated')
    searchQuery.value = ''
    searchResults.value = []
  } catch (e) {
    alert(e.response?.data?.detail || 'Failed to add member')
  }
}

// Reset management state when panel closes
watch(() => props.visible, (val) => {
  if (!val) {
    managingGroup.value = null
  }
})
</script>

<style scoped>
.group-panel {
  position: fixed;
  right: 0;
  top: 0;
  width: 350px;
  height: 100vh;
  background: white;
  box-shadow: -4px 0 20px rgba(0,0,0,0.1);
  z-index: 100;
  overflow-y: auto;
  padding: 1rem;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

.close-btn {
  background: none;
  border: none;
  font-size: 1.5rem;
  cursor: pointer;
  color: #666;
}

.section {
  margin-bottom: 1.5rem;
}

.section h4 {
  color: #333;
  margin-bottom: 0.5rem;
}

.section h5 {
  color: #555;
  margin-bottom: 0.4rem;
  font-size: 0.9rem;
}

.section input {
  width: 100%;
  padding: 0.5rem;
  border: 1px solid #ddd;
  border-radius: 6px;
  margin-bottom: 0.5rem;
  outline: none;
  box-sizing: border-box;
}

.section button {
  width: 100%;
  padding: 0.5rem;
  background: #667eea;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
}

.section button:disabled {
  opacity: 0.5;
}

.group-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem;
  border: 1px solid #eee;
  border-radius: 8px;
  margin-bottom: 0.5rem;
}

.group-actions {
  display: flex;
  gap: 0.25rem;
}

.group-actions button {
  width: auto;
  padding: 0.25rem 0.6rem;
  font-size: 0.8rem;
  border-radius: 4px;
}

.manage-btn {
  background: #48bb78 !important;
}

.members-list {
  margin-bottom: 1rem;
}

.member-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.4rem 0.5rem;
  border-bottom: 1px solid #f0f0f0;
  font-size: 0.9rem;
}

.role-badge {
  font-size: 0.7rem;
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
  color: white;
}

.role-badge.admin {
  background: #e53e3e;
}

.role-badge.member {
  background: #718096;
}

.search-results {
  max-height: 200px;
  overflow-y: auto;
  border: 1px solid #eee;
  border-radius: 6px;
  margin-bottom: 0.5rem;
}

.search-result-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.4rem 0.5rem;
  border-bottom: 1px solid #f5f5f5;
  font-size: 0.9rem;
}

.search-result-item button {
  width: auto;
  padding: 0.2rem 0.5rem;
  font-size: 0.75rem;
  border-radius: 4px;
}

.error-msg {
  color: #e53e3e;
  font-size: 0.85rem;
}

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
</style>
