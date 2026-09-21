<template>
  <div class="message-bubble" :class="{ own: isOwn }">
    <div class="sender" v-if="!isOwn">{{ senderName }}</div>
    <div class="bubble">
      <p>{{ message.content }}</p>
      <span class="time">{{ formatTime(message.timestamp) }}</span>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  message: { type: Object, required: true },
  isOwn: { type: Boolean, default: false },
  senderName: { type: String, default: '' },
})

function formatTime(timestamp) {
  return new Date(timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}
</script>

<style scoped>
.message-bubble {
  display: flex;
  flex-direction: column;
  margin-bottom: 12px;
  max-width: 70%;
}

.message-bubble.own {
  margin-left: auto;
  align-items: flex-end;
}

.sender {
  font-size: 0.75rem;
  color: #666;
  margin-bottom: 2px;
  padding-left: 12px;
}

.bubble {
  padding: 10px 14px;
  border-radius: 18px;
  background: #e9ecef;
  color: #333;
  position: relative;
}

.own .bubble {
  background: #667eea;
  color: white;
}

.bubble p {
  margin: 0;
  word-wrap: break-word;
  line-height: 1.4;
}

.time {
  font-size: 0.7rem;
  opacity: 0.7;
  display: block;
  text-align: right;
  margin-top: 4px;
}
</style>
