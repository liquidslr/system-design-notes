<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  createComment, deleteComment, extractError, listReplies, voteComment,
} from '../api'
import { authState, hasRole } from '../auth'

const props = defineProps({ comment: { type: Object, required: true } })
const emit = defineEmits(['deleted'])
const route = useRoute()
const router = useRouter()

// The parent holds these objects in a reactive array, so mutating fields here
// updates the list in place (vote counts, reply_count) without re-fetching.
const c = props.comment
const isReply = computed(() => !!c.root_id)
const canDelete = computed(() =>
  !!authState.user && (authState.user.id === c.author.id || hasRole('moderator')))

const voteError = ref('')
const showReplies = ref(false)
const replies = ref([])
const repliesTotal = ref(0)
const repliesLoaded = ref(false)
const replyLoading = ref(false)
const replyOpen = ref(false)
const replyDraft = ref('')

function fmtDate(ts) {
  return ts ? new Date(ts * 1000).toLocaleString() : ''
}

function gotoLogin() {
  router.push({ path: '/login', query: { redirect: route.fullPath } })
}

async function vote(value) {
  if (!authState.user) { gotoLogin(); return }
  voteError.value = ''
  try {
    const { data } = await voteComment(c.id, value)
    c.like_count = data.like_count
    c.dislike_count = data.dislike_count
    c.score = data.score
    c.my_vote = data.my_vote
  } catch (e) {
    voteError.value = extractError(e, 'Vote failed')
  }
}

async function loadReplies() {
  replyLoading.value = true
  try {
    const { data } = await listReplies(c.id, { limit: 50, offset: 0 })
    replies.value = data.comments
    repliesTotal.value = data.total
    repliesLoaded.value = true
  } catch (e) {
    voteError.value = extractError(e, 'Could not load replies')
  } finally {
    replyLoading.value = false
  }
}

function toggleReplies() {
  showReplies.value = !showReplies.value
  if (showReplies.value && !repliesLoaded.value) loadReplies()
}

async function submitReply() {
  if (!authState.user) { gotoLogin(); return }
  const text = replyDraft.value.trim()
  if (!text) return
  try {
    const { data } = await createComment(c.video_id, text, c.id)
    replies.value.push(data)
    repliesTotal.value += 1
    c.reply_count += 1
    replyDraft.value = ''
    showReplies.value = true
    repliesLoaded.value = true
  } catch (e) {
    voteError.value = extractError(e, 'Could not reply')
  }
}

async function remove() {
  try {
    await deleteComment(c.id)
    emit('deleted', c.id)
  } catch (e) {
    voteError.value = extractError(e, 'Could not delete')
  }
}
</script>

<template>
  <div class="comment">
    <div class="comment-head">
      <span class="comment-author">{{ c.author.username }}</span>
      <span class="comment-date">{{ fmtDate(c.created_at) }}</span>
    </div>
    <p class="comment-body" :class="{ deleted: c.status === 'deleted' }">{{ c.content }}</p>

    <div v-if="voteError" class="error-box">{{ voteError }}</div>

    <div class="comment-actions">
      <button class="vote" :class="{ on: c.my_vote === 1 }"
              :disabled="c.status === 'deleted'" @click="vote(1)">
        👍 {{ c.like_count }}
      </button>
      <button class="vote" :class="{ on: c.my_vote === -1 }"
              :disabled="c.status === 'deleted'" @click="vote(-1)">
        👎 {{ c.dislike_count }}
      </button>
      <template v-if="c.status === 'active' && !isReply">
        <button class="link" @click="replyOpen = !replyOpen">Reply</button>
        <button v-if="c.reply_count || showReplies" class="link" @click="toggleReplies">
          {{ showReplies ? 'Hide' : 'View' }} {{ c.reply_count || repliesTotal }}
          {{ (c.reply_count || repliesTotal) === 1 ? 'reply' : 'replies' }}
        </button>
      </template>
      <button v-if="canDelete" class="link danger" @click="remove">Delete</button>
    </div>

    <div v-if="replyOpen && !isReply" class="comment-form reply-form">
      <textarea v-model="replyDraft" rows="2"
                :placeholder="authState.user ? 'Write a reply…' : 'Sign in to reply'"></textarea>
      <div class="comment-form-actions">
        <button class="btn secondary" @click="replyOpen = false">Cancel</button>
        <button class="btn" :disabled="!replyDraft.trim()" @click="submitReply">Reply</button>
      </div>
    </div>

    <div v-if="showReplies" class="replies">
      <p v-if="replyLoading" class="comments-empty">Loading replies…</p>
      <CommentItem v-for="r in replies" :key="r.id" :comment="r" />
      <p v-if="!replyLoading && repliesLoaded && !replies.length" class="comments-empty">
        No replies yet.
      </p>
    </div>
  </div>
</template>
