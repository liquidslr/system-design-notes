import { ref, onUnmounted } from 'vue'
import { useChatStore } from '../stores/chat'

const WS_URL = 'ws://localhost:8001/ws'

export function useWebSocket(token) {
  const chatStore = useChatStore()
  const ws = ref(null)
  const isConnected = ref(false)
  const reconnectAttempts = ref(0)
  const maxReconnectAttempts = 10

  function connect() {
    const url = `${WS_URL}?token=${token}`
    ws.value = new WebSocket(url)

    ws.value.onopen = () => {
      isConnected.value = true
      reconnectAttempts.value = 0
      console.log('WebSocket connected')
    }

    ws.value.onmessage = async (event) => {
      const data = JSON.parse(event.data)

      if (data.type === 'new_message') {
        const msg = data.message
        const channelId = getChannelId(msg)
        chatStore.addMessage(channelId, msg)
      } else if (data.type === 'message_sync') {
        data.messages.forEach(msg => {
          const channelId = getChannelId(msg)
          chatStore.addMessage(channelId, msg)
        })
      } else if (data.type === 'presence_update') {
        chatStore.updateOnlineStatus(data.user_id, data.status)
      } else if (data.type === 'group_invite') {
        await chatStore.fetchGroups()
      } else if (data.type === 'error') {
        console.error('WebSocket error:', data.message)
      }
    }

    ws.value.onclose = () => {
      isConnected.value = false
      attemptReconnect()
    }

    ws.value.onerror = (error) => {
      console.error('WebSocket error:', error)
    }
  }

  function attemptReconnect() {
    if (reconnectAttempts.value < maxReconnectAttempts) {
      const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.value), 30000)
      reconnectAttempts.value++
      console.log(`Reconnecting in ${delay}ms (attempt ${reconnectAttempts.value})`)
      setTimeout(connect, delay)
    }
  }

  function send(data) {
    if (ws.value && ws.value.readyState === WebSocket.OPEN) {
      ws.value.send(JSON.stringify(data))
    }
  }

  function sendMessage(receiverId, content, channelType = 'one_to_one') {
    send({
      type: 'send_message',
      receiver_id: receiverId,
      content: content,
      channel_type: channelType,
    })
  }

  function syncMessages(channelId, lastMessageId) {
    send({
      type: 'sync',
      channel_id: channelId,
      last_message_id: lastMessageId,
    })
  }

  function disconnect() {
    if (ws.value) {
      ws.value.close()
      ws.value = null
    }
  }

  function getChannelId(msg) {
    if (msg.channel_type === 'group') {
      return msg.receiver_id
    }
    const ids = [msg.sender_id, msg.receiver_id].sort()
    return ids.join('_')
  }

  function getCurrentUserId() {
    try {
      const payload = JSON.parse(atob(token.split('.')[1]))
      return payload.sub
    } catch {
      return null
    }
  }

  onUnmounted(() => {
    disconnect()
  })

  return {
    connect, disconnect, send, sendMessage, syncMessages,
    isConnected, ws,
  }
}
