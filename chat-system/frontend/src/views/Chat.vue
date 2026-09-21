<template>
  <div class="chat-layout">
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

    <ChatWindow
      :channel="chatStore.activeChannel"
      :messages="currentMessages"
      :current-user-id="currentUserId"
      :peer-status="peerStatus"
      @send="sendMessage"
      @typing="sendTyping"
    />

    <GroupPanel
      :visible="showGroupPanel"
      :groups="chatStore.groups"
      :current-user-id="currentUserId"
      @close="showGroupPanel = false"
      @select-group="selectGroup"
      @group-created="refreshGroups"
    />

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
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import axios from 'axios'
import { useAuthStore } from '../stores/auth'
import { useChatStore } from '../stores/chat'
import { useWebSocket } from '../composables/useWebSocket'
import ChatSidebar from '../components/ChatSidebar.vue'
import ChatWindow from '../components/ChatWindow.vue'
import GroupPanel from '../components/GroupPanel.vue'

const authStore = useAuthStore()
const chatStore = useChatStore()
const showGroupPanel = ref(false)
const showInviteModal = ref(false)
const inviteGroup = ref(null)
const selectedInvitees = ref([])
const friendsNotInGroup = ref([])

const currentUserId = computed(() => authStore.user?.id || '')
const currentMessages = computed(() => {
  if (!chatStore.activeChannel) return []
  const id = chatStore.activeChannel.type === 'one_to_one'
    ? getChannelId(chatStore.activeChannel.id)
    : chatStore.activeChannel.id
  return chatStore.conversations[id] || []
})

const peerStatus = computed(() => {
  if (chatStore.activeChannel?.type === 'one_to_one') {
    return chatStore.onlineStatuses[chatStore.activeChannel.id] || 'offline'
  }
  return 'offline'
})

// WebSocket setup
const ws = useWebSocket(authStore.token)

function getChannelId(otherUserId) {
  const ids = [currentUserId.value, otherUserId].sort()
  return ids.join('_')
}

function selectFriend(friend) {
  const channelId = getChannelId(friend.user_id)
  chatStore.setActiveChannel('one_to_one', friend.user_id, friend.nickname || friend.username)
  chatStore.loadMessages(channelId, 'one_to_one')
}

function selectGroup(group) {
  chatStore.setActiveChannel('group', group.id, group.name)
  chatStore.loadMessages(group.id, 'group')
  showGroupPanel.value = false
}

function startChat(user) {
  selectFriend({ user_id: user.id, nickname: user.nickname, username: user.username, online_status: 'offline' })
}

function sendMessage(content) {
  if (!chatStore.activeChannel) return
  const receiverId = chatStore.activeChannel.id
  const channelType = chatStore.activeChannel.type
  ws.sendMessage(receiverId, content, channelType)
}

function sendTyping() {
  // Could send typing indicator
}

async function refreshGroups() {
  await chatStore.fetchGroups()
}

async function refreshAll() {
  await Promise.all([
    chatStore.fetchFriends(),
    chatStore.fetchPendingRequests(),
    chatStore.fetchSentRequests(),
  ])
}

async function openInviteModal(group) {
  inviteGroup.value = group
  showInviteModal.value = true
  selectedInvitees.value = []

  try {
    const membersRes = await axios.get(`/api/groups/${group.id}/members`)
    const memberIds = new Set(membersRes.data.map(m => m.user_id))
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

onMounted(async () => {
  await authStore.fetchProfile()
  ws.connect()
  await refreshAll()
  await chatStore.fetchGroups()
})
</script>

<style scoped>
.chat-layout {
  display: flex;
  height: 100vh;
  background: #f0f2f5;
}

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
</style>
