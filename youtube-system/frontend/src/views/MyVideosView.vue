<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { extractError, listMyVideos, resubmitVideo, retryVideo } from '../api'

const router = useRouter()
const videos = ref([])
const error = ref('')
const busyId = ref('')
let timer = null

function fmtDuration(sec) {
  if (!sec) return ''
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

function fmtDate(ts) {
  return ts ? new Date(ts * 1000).toLocaleString() : ''
}

async function refresh() {
  try {
    const { data } = await listMyVideos()
    videos.value = data.videos
  } catch (e) {
    error.value = extractError(e, 'Could not load your videos')
  }
}

async function doRetry(id) {
  busyId.value = id
  error.value = ''
  try {
    await retryVideo(id)
    await refresh()
  } catch (e) {
    error.value = extractError(e, 'Retry failed')
  } finally {
    busyId.value = ''
  }
}

async function doResubmit(v) {
  busyId.value = v.id
  error.value = ''
  try {
    await resubmitVideo(v.id, v.title, v.description || '')
    await refresh()
  } catch (e) {
    error.value = extractError(e, 'Resubmit failed')
  } finally {
    busyId.value = ''
  }
}

onMounted(() => {
  refresh()
  // Poll only while something is still in flight; the backend drives statuses.
  timer = setInterval(() => {
    if (videos.value.some((v) => v.status === 'pending' || v.status === 'processing')) {
      refresh()
    }
  }, 4000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div>
    <h2 style="margin-top: 0">My videos</h2>
    <div v-if="error" class="error-box">{{ error }}</div>

    <div v-if="videos.length === 0" class="empty-state">
      <p>You have not uploaded anything yet.</p>
      <RouterLink to="/upload" class="btn">Upload your first video</RouterLink>
    </div>

    <div class="grid">
      <div v-for="v in videos" :key="v.id" class="card" @click="router.push(`/watch/${v.id}`)">
        <img v-if="v.thumbnail_url" class="thumb" :src="v.thumbnail_url" alt="" />
        <div v-else class="thumb-placeholder">🎬</div>
        <div class="card-body">
          <p class="card-title">{{ v.title }}</p>
          <div class="card-meta">
            <span class="badge" :class="v.status">{{ v.status }}</span>
            <span v-if="v.moderation_status === 'pending_review'" class="badge pending_review">审核中</span>
            <span v-else-if="v.moderation_status === 'rejected'" class="badge rejected" :title="v.rejection_reason">已拒绝</span>
            <span v-if="v.duration_sec"> · {{ fmtDuration(v.duration_sec) }}</span>
          </div>
          <p class="uploader">{{ fmtDate(v.created_at) }}</p>
          <button
            v-if="v.status === 'failed'"
            class="btn tiny"
            style="margin-top: 8px"
            :disabled="busyId === v.id"
            @click.stop="doRetry(v.id)"
          >
            {{ busyId === v.id ? 'Retrying…' : 'Retry transcode' }}
          </button>
          <button
            v-if="v.moderation_status === 'rejected'"
            class="btn tiny"
            style="margin-top: 8px"
            :disabled="busyId === v.id"
            @click.stop="doResubmit(v)"
          >
            {{ busyId === v.id ? 'Submitting…' : 'Resubmit' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
