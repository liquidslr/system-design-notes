<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { createVideo, extractError, getUploadUrl, uploadBinary } from '../api'
import { authState, hasRole } from '../auth'

const router = useRouter()
const file = ref(null)
const title = ref('')
const description = ref('')
const progress = ref(0)
const uploading = ref(false)
const error = ref('')
const dragging = ref(false)

// A signed-in 'user' passes the route guard but still lacks upload rights;
// explain it inline instead of letting a raw backend 403 surface.
const canUpload = computed(() => hasRole('creator'))

function pickFile(f) {
  if (f) {
    file.value = f
    if (!title.value) title.value = f.name.replace(/\.[^.]+$/, '')
  }
}
function onDrop(e) {
  dragging.value = false
  pickFile(e.dataTransfer.files[0])
}

async function submit() {
  error.value = ''
  if (!canUpload.value) {
    error.value = 'Uploading requires the creator role'
    return
  }
  if (!file.value) { error.value = 'Please choose a video file'; return }
  if (!title.value.trim()) { error.value = 'Title is required'; return }

  uploading.value = true
  progress.value = 0
  try {
    // Step 1: pre-signed upload URL (design doc: binary bypasses API logic)
    const { data: presign } = await getUploadUrl(
      file.value.name, file.value.size, file.value.type)

    // Step 2: upload binary (streams to storage)
    const onProgress = (e) => {
      if (e.total) progress.value = Math.round((e.loaded / e.total) * 100)
    }
    await uploadBinary(presign.upload_path, file.value, onProgress)

    // Step 3: register metadata -> enqueues the transcode task
    await createVideo(presign.video_id, title.value, description.value, file.value.name)

    router.push('/')
  } catch (e) {
    error.value = e?.response?.status === 403
      ? 'Uploading requires the creator role. Ask an admin to promote your account.'
      : extractError(e, 'Upload failed')
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <div style="max-width: 560px; margin: 0 auto">
    <h2>Upload a video</h2>

    <div v-if="!canUpload" class="hint-box">
      Your account has the <strong>{{ authState.user?.role }}</strong> role.
      Uploading requires <strong>creator</strong> or above — ask an admin to
      promote you, then sign in again.
    </div>

    <div
      class="dropzone"
      :class="{ over: dragging }"
      @click="$refs.fileInput.click()"
      @dragover.prevent="dragging = true"
      @dragleave="dragging = false"
      @drop.prevent="onDrop"
    >
      <p v-if="file">{{ file.name }} ({{ (file.size / 1024 / 1024).toFixed(1) }} MB)</p>
      <p v-else>Drag & drop a video here, or click to browse<br />
        <small>mp4 / mov / avi / mkv / webm · max 1GB</small>
      </p>
      <input
        ref="fileInput"
        type="file"
        accept="video/*"
        style="display: none"
        @change="pickFile($event.target.files[0])"
      />
    </div>

    <div class="field" style="margin-top: 20px">
      <label>Title</label>
      <input v-model="title" placeholder="Video title" />
    </div>
    <div class="field">
      <label>Description (optional)</label>
      <textarea v-model="description" placeholder="Tell viewers about your video"></textarea>
    </div>

    <div v-if="error" class="error-box">{{ error }}</div>

    <div v-if="uploading" class="progress">
      <div class="progress-bar" :style="{ width: progress + '%' }"></div>
    </div>
    <p v-if="uploading" style="color: var(--text-dim); font-size: 13px">
      Uploading… {{ progress }}%
    </p>

    <button class="btn" :disabled="uploading || !canUpload" @click="submit">
      {{ uploading ? 'Uploading…' : 'Upload' }}
    </button>
  </div>
</template>
