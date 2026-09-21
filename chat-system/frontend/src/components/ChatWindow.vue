<template>
  <div class="chat-window">
    <div class="chat-header" v-if="channel">
      <h3>{{ channel.name }}</h3>
      <OnlineIndicator v-if="channel.type === 'one_to_one'" :status="peerStatus" />
    </div>
    <div class="chat-header" v-else>
      <h3>Select a conversation</h3>
    </div>

    <div class="messages" ref="messagesContainer">
      <MessageBubble
        v-for="msg in messages"
        :key="msg.message_id"
        :message="msg"
        :is-own="msg.sender_id === currentUserId"
        :sender-name="getSenderName(msg.sender_id)"
      />
      <p v-if="!messages.length && channel" class="empty-chat">No messages yet. Say hello!</p>
    </div>

    <div class="input-area" v-if="channel">
      <input
        v-model="newMessage"
        placeholder="Type a message..."
        @keyup.enter="sendMsg"
        @keyup="sendTyping"
      />
      <button @click="sendMsg" :disabled="!newMessage.trim()">Send</button>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import MessageBubble from './MessageBubble.vue'
import OnlineIndicator from './OnlineIndicator.vue'

const props = defineProps({
  channel: Object,
  messages: Array,
  currentUserId: String,
  peerStatus: { type: String, default: 'offline' },
})

const emit = defineEmits(['send', 'typing'])

const newMessage = ref('')
const messagesContainer = ref(null)

function sendMsg() {
  if (!newMessage.value.trim()) return
  emit('send', newMessage.value.trim())
  newMessage.value = ''
}

function sendTyping() {
  emit('typing')
}

function getSenderName(senderId) {
  return senderId === props.currentUserId ? 'You' : senderId.substring(0, 8)
}

watch(() => props.messages?.length, () => {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
})
</script>

<style scoped>
.chat-window {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #f8f9fa;
}

.chat-header {
  padding: 1rem;
  background: white;
  border-bottom: 1px solid #eee;
  display: flex;
  align-items: center;
  gap: 8px;
}

.chat-header h3 { font-size: 1.1rem; color: #333; }

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 1rem;
}

.empty-chat {
  text-align: center;
  color: #999;
  margin-top: 2rem;
}

.input-area {
  display: flex;
  padding: 1rem;
  background: white;
  border-top: 1px solid #eee;
  gap: 0.5rem;
}

.input-area input {
  flex: 1;
  padding: 0.75rem 1rem;
  border: 1px solid #ddd;
  border-radius: 24px;
  outline: none;
  font-size: 0.95rem;
}

.input-area input:focus {
  border-color: #667eea;
}

.input-area button {
  padding: 0.75rem 1.5rem;
  background: #667eea;
  color: white;
  border: none;
  border-radius: 24px;
  cursor: pointer;
  font-size: 0.95rem;
}

.input-area button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
