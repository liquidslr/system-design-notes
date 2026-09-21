import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

const API_BASE = '/api'

export const useChatStore = defineStore('chat', () => {
  const friends = ref([])
  const groups = ref([])
  const pendingRequests = ref([]) // incoming pending requests
  const sentRequests = ref([])    // outgoing pending requests
  const conversations = ref({})  // channelId -> messages[]
  const activeChannel = ref(null) // { type: 'one_to_one'|'group', id: string, name: string }
  const onlineStatuses = ref({}) // userId -> 'online'|'offline'

  async function fetchFriends() {
    const res = await axios.get(`${API_BASE}/friends`)
    friends.value = res.data
    res.data.forEach(f => {
      onlineStatuses.value[f.user_id] = f.online_status
    })
  }

  async function fetchGroups() {
    try {
      const res = await axios.get(`${API_BASE}/groups/my-groups`)
      groups.value = res.data
    } catch {
      groups.value = []
    }
  }

  async function fetchPendingRequests() {
    try {
      const res = await axios.get(`${API_BASE}/friends/pending-requests`)
      pendingRequests.value = res.data
    } catch {
      pendingRequests.value = []
    }
  }

  async function fetchSentRequests() {
    try {
      const res = await axios.get(`${API_BASE}/friends/sent-requests`)
      sentRequests.value = res.data
    } catch {
      sentRequests.value = []
    }
  }

  async function acceptRequest(userId) {
    await axios.put(`${API_BASE}/friends/${userId}/accept`)
    pendingRequests.value = pendingRequests.value.filter(r => r.user_id !== userId)
    await fetchFriends()
  }

  async function rejectRequest(userId) {
    await axios.put(`${API_BASE}/friends/${userId}/reject`)
    pendingRequests.value = pendingRequests.value.filter(r => r.user_id !== userId)
  }

  async function cancelRequest(userId) {
    await axios.delete(`${API_BASE}/friends/${userId}/cancel`)
    sentRequests.value = sentRequests.value.filter(r => r.user_id !== userId)
  }

  async function loadMessages(channelId, channelType) {
    let url
    if (channelType === 'one_to_one') {
      url = `${API_BASE}/channels/${channelId}/messages`
    } else {
      url = `${API_BASE}/groups/${channelId}/messages`
    }
    const res = await axios.get(url)
    conversations.value[channelId] = res.data
  }

  function addMessage(channelId, message) {
    if (!conversations.value[channelId]) {
      conversations.value[channelId] = []
    }
    conversations.value[channelId].push(message)
  }

  function setActiveChannel(type, id, name) {
    activeChannel.value = { type, id, name }
  }

  function updateOnlineStatus(userId, status) {
    onlineStatuses.value[userId] = status
  }

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

  return {
    friends, groups, pendingRequests, sentRequests,
    conversations, activeChannel, onlineStatuses,
    fetchFriends, fetchGroups, fetchPendingRequests, fetchSentRequests,
    acceptRequest, rejectRequest, cancelRequest,
    loadMessages, addMessage, setActiveChannel, updateOnlineStatus,
    fetchMembersWithStatus, inviteToGroup,
  }
})
