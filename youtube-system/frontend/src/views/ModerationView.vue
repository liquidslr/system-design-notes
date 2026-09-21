<script setup>
import { onMounted, ref } from 'vue'
import { approveVideo, extractError, listModerationQueue, rejectVideo } from '../api'

const videos = ref([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
const busyId = ref('')
const rejectInputs = ref({})
const showRejectForm = ref({})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await listModerationQueue(50, 0)
    videos.value = data.videos
    total.value = data.total
  } catch (e) {
    error.value = extractError(e, 'Failed to load queue')
  } finally {
    loading.value = false
  }
}

async function doApprove(id) {
  busyId.value = id
  error.value = ''
  try {
    await approveVideo(id)
    videos.value = videos.value.filter((v) => v.id !== id)
    total.value--
  } catch (e) {
    error.value = extractError(e, 'Approve failed')
  } finally {
    busyId.value = ''
  }
}

function toggleReject(id) {
  showRejectForm.value[id] = !showRejectForm.value[id]
  if (!rejectInputs.value[id]) rejectInputs.value[id] = ''
}

async function doReject(id) {
  const reason = (rejectInputs.value[id] || '').trim()
  if (!reason) { error.value = 'Rejection reason is required'; return }
  busyId.value = id
  error.value = ''
  try {
    await rejectVideo(id, reason)
    videos.value = videos.value.filter((v) => v.id !== id)
    total.value--
    delete showRejectForm.value[id]
  } catch (e) {
    error.value = extractError(e, 'Reject failed')
  } finally {
    busyId.value = ''
  }
}

onMounted(load)
</script>

<template>
  <div class="moderation-page">
    <h2 style="margin-top: 0">Moderation Queue</h2>
    <div v-if="error" class="error-box">{{ error }}</div>
    <p v-if="loading" class="mod-loading">Loading…</p>
    <p v-else-if="videos.length === 0" class="empty-state">No videos pending review.</p>

    <div v-for="v in videos" :key="v.id" class="mod-item">
      <div class="mod-info">
        <RouterLink :to="`/watch/${v.id}`" class="mod-title">{{ v.title }}</RouterLink>
        <span class="mod-meta">
          by {{ v.uploader?.username || 'Anonymous' }} · {{ new Date(v.created_at * 1000).toLocaleString() }}
        </span>
      </div>
      <div class="mod-actions">
        <button class="btn" :disabled="busyId === v.id" @click="doApprove(v.id)">
          {{ busyId === v.id ? '…' : 'Approve' }}
        </button>
        <button class="btn secondary" @click="toggleReject(v.id)">Reject</button>
      </div>
      <div v-if="showRejectForm[v.id]" class="mod-reject-form">
        <input
          v-model="rejectInputs[v.id]"
          placeholder="Reason (required)"
          maxlength="500"
          @keyup.enter="doReject(v.id)"
        />
        <button class="btn" :disabled="busyId === v.id" @click="doReject(v.id)">Confirm Reject</button>
      </div>
    </div>
    <p v-if="total > videos.length" class="mod-summary">
      {{ videos.length }} of {{ total }} shown.
    </p>
  </div>
</template>
