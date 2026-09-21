<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { listVideos } from '../api'

const router = useRouter()
const videos = ref([])
let timer = null

function uploaderName(v) {
  return v.uploader?.username || 'Anonymous'
}

function fmtDuration(sec) {
  if (!sec) return ''
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

async function refresh() {
  try {
    const { data } = await listVideos()
    videos.value = data.videos
  } catch { /* keep previous list on transient errors */ }
}

onMounted(() => {
  refresh()
  timer = setInterval(refresh, 5000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <div>
    <div v-if="videos.length === 0" class="empty-state">
      <p>No videos yet.</p>
    </div>
    <div class="grid">
      <div
        v-for="v in videos"
        :key="v.id"
        class="card"
        @click="router.push(`/watch/${v.id}`)"
      >
        <img v-if="v.thumbnail_url" class="thumb" :src="v.thumbnail_url" alt="" />
        <div v-else class="thumb-placeholder">🎬</div>
        <div class="card-body">
          <p class="card-title">{{ v.title }}</p>
          <p class="uploader">{{ uploaderName(v) }}</p>
          <div class="card-meta">
            <span class="badge" :class="v.status">{{ v.status }}</span>
            <span v-if="v.duration_sec"> · {{ fmtDuration(v.duration_sec) }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
