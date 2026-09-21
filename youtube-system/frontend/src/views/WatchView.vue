<script setup>
import { computed, ref, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import Hls from 'hls.js'
import Comments from '../components/Comments.vue'
import { extractError, getVideo, retryVideo } from '../api'
import { authState, getAccess, hasRole } from '../auth'

const route = useRoute()
const video = ref(null)
const error = ref('')
const videoEl = ref(null)
const hlsPlayer = ref(null)
const levels = ref([])
const currentLevel = ref(-1)
const started = ref(false)
let timer = null

const uploaderName = computed(() => video.value?.uploader?.username || 'Anonymous')

// Owner or staff (moderator+) may retry - mirrors the backend rule exactly.
const canRetry = computed(() => {
  const me = authState.user
  if (!me || !video.value) return false
  return video.value.uploader?.id === me.id || hasRole('moderator')
})

async function load() {
  try {
    const { data } = await getVideo(route.params.id)
    video.value = data
    error.value = ''
    if (data.status === 'ready' && data.stream_url && !started.value) {
      started.value = true
      // the <video> element lives under v-if="video" and is only mounted after
      // Vue flushes this update; wait for it before initializing the player
      await nextTick()
      play(data.stream_url)
    }
    if (data.status === 'ready' && timer) {
      clearInterval(timer)
      timer = null
    }
  } catch (e) {
    error.value = extractError(e)
  }
}

function play(url) {
  const el = videoEl.value
  if (!el) return
  if (Hls.isSupported()) {
    const hls = new Hls({
      xhrSetup: (xhr, reqUrl) => {
        if (reqUrl.includes('/api/keys/')) {
          const token = getAccess()
          if (token) xhr.setRequestHeader('Authorization', 'Bearer ' + token)
        }
      }
    })
    hlsPlayer.value = hls
    hls.loadSource(url)
    hls.attachMedia(el)
    hls.on(Hls.Events.MANIFEST_PARSED, () => {
      levels.value = hls.levels.map((l, i) => ({ i, height: l.height }))
      hls.currentLevel = -1 // auto by default
    })
    hls.on(Hls.Events.ERROR, (_evt, data) => {
      if (!data.fatal) return
      if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
        error.value = 'Unable to fetch decryption key – please log in and retry'
        hls.startLoad()
      } else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
        hls.recoverMediaError()
      } else {
        error.value = 'Playback failed: ' + data.details
      }
    })
  } else if (el.canPlayType('application/vnd.apple.mpegurl')) {
    el.src = url // Safari native HLS (no custom key auth)
  }
}

function setLevel(i) {
  currentLevel.value = i
  if (hlsPlayer.value) hlsPlayer.value.currentLevel = i
}

async function doRetry() {
  try {
    await retryVideo(route.params.id)
    await load()
    if (!timer) timer = setInterval(load, 3000)
  } catch (e) {
    error.value = extractError(e)
  }
}

onMounted(() => {
  load()
  timer = setInterval(load, 3000)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
  if (hlsPlayer.value) hlsPlayer.value.destroy()
})
</script>

<template>
  <div v-if="video">
    <div class="watch-layout">
      <div>
        <div class="player-box">
          <video ref="videoEl" controls></video>
          <div v-if="authState.user" class="watermark">{{ authState.user.username }}</div>
        </div>
        <div v-if="video.moderation_status === 'pending_review'" class="badge pending_review moderation-banner">
          Under review – only you (owner) and moderators can see this page
        </div>
        <div v-else-if="video.moderation_status === 'rejected'" class="error-box moderation-banner">
          Rejected: {{ video.rejection_reason }}
        </div>
        <h2 style="margin: 14px 0 4px">{{ video.title }}</h2>
        <p class="uploader">👤 {{ uploaderName }}</p>
        <p style="color: var(--text-dim)">{{ video.description }}</p>

        <div v-if="video.status === 'processing'" class="badge processing">
          Transcoding… page refreshes automatically
        </div>
        <div v-else-if="video.status === 'pending'" class="badge pending">
          Queued for transcoding
        </div>
        <div v-else-if="video.status === 'failed'" class="error-box">
          Transcoding failed: {{ video.error_msg }}
          <button v-if="canRetry" class="btn" style="margin-left: 12px" @click="doRetry">
            Retry
          </button>
        </div>

        <div v-if="levels.length" style="margin-top: 12px">
          Quality:
          <select @change="setLevel(+$event.target.value)">
            <option value="-1" :selected="currentLevel === -1">Auto</option>
            <option
              v-for="l in levels"
              :key="l.i"
              :value="l.i"
              :selected="currentLevel === l.i"
            >
              {{ l.height }}p
            </option>
          </select>
        </div>

        <Comments :video-id="route.params.id" />
      </div>

      <aside>
        <h3 style="font-size: 15px; margin-top: 0">Renditions</h3>
        <div v-if="video.renditions" class="rendition-list">
          <div v-for="r in video.renditions" :key="r.resolution" class="rendition-item">
            <span>{{ r.resolution }}</span>
            <span style="color: var(--text-dim)">
              {{ r.bitrate_kbps }} kbps · {{ r.status }}
            </span>
          </div>
        </div>
        <p v-else style="color: var(--text-dim); font-size: 13px">
          Available when the video is ready.
        </p>
      </aside>
    </div>
  </div>
  <div v-else-if="error" class="error-box">{{ error }}</div>
  <div v-else class="empty-state">Loading…</div>
</template>
