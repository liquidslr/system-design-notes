<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { createComment, extractError, listComments } from '../api'
import { authState } from '../auth'
import CommentItem from './CommentItem.vue'

const props = defineProps({ videoId: { type: String, required: true } })
const route = useRoute()
const router = useRouter()

const PAGE = 20
const comments = ref([])
const total = ref(0)
const sort = ref('top')
const error = ref('')
const loading = ref(false)
const draft = ref('')
const submitting = ref(false)

const canLoadMore = () => comments.value.length < total.value

async function load(reset = false) {
  loading.value = true
  error.value = ''
  try {
    const offset = reset ? 0 : comments.value.length
    const { data } = await listComments(
      props.videoId, { sort: sort.value, limit: PAGE, offset })
    total.value = data.total
    comments.value = reset ? data.comments : comments.value.concat(data.comments)
  } catch (e) {
    error.value = extractError(e, 'Could not load comments')
  } finally {
    loading.value = false
  }
}

function changeSort(s) {
  if (sort.value === s) return
  sort.value = s
  load(true)
}

function gotoLogin() {
  router.push({ path: '/login', query: { redirect: route.fullPath } })
}

async function submit() {
  if (!authState.user) { gotoLogin(); return }
  const text = draft.value.trim()
  if (!text) return
  submitting.value = true
  error.value = ''
  try {
    const { data } = await createComment(props.videoId, text)
    comments.value.unshift(data)
    total.value += 1
    draft.value = ''
  } catch (e) {
    error.value = extractError(e, 'Could not post comment')
  } finally {
    submitting.value = false
  }
}

function onDeleted(id) {
  comments.value = comments.value.filter((c) => c.id !== id)
  total.value = Math.max(0, total.value - 1)
}

onMounted(() => load(true))
watch(() => props.videoId, () => load(true))
</script>

<template>
  <section class="comments">
    <h3>Comments <small v-if="total">({{ total }})</small></h3>

    <div class="comment-form">
      <textarea
        v-model="draft"
        rows="2"
        :placeholder="authState.user ? 'Add a comment…' : 'Sign in to comment'"
        @focus="!authState.user && gotoLogin()"
      ></textarea>
      <div class="comment-form-actions">
        <button class="btn" :disabled="submitting || !authState.user" @click="submit">
          {{ authState.user ? (submitting ? 'Posting…' : 'Comment') : 'Sign in' }}
        </button>
      </div>
    </div>

    <div v-if="error" class="error-box">{{ error }}</div>

    <div class="comment-sort">
      <button :class="{ active: sort === 'top' }" @click="changeSort('top')">Top</button>
      <button :class="{ active: sort === 'new' }" @click="changeSort('new')">Newest</button>
    </div>

    <p v-if="!comments.length && !loading" class="comments-empty">No comments yet.</p>

    <CommentItem v-for="c in comments" :key="c.id" :comment="c" @deleted="onDeleted" />

    <button
      v-if="canLoadMore()"
      class="btn secondary"
      style="margin-top: 12px"
      :disabled="loading"
      @click="load()"
    >
      {{ loading ? 'Loading…' : `Load more (${comments.length}/${total})` }}
    </button>
  </section>
</template>
