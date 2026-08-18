<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NResult, NIcon } from 'naive-ui'
import { ArrowBackOutline, ArrowForwardOutline } from '@vicons/ionicons5'
import MarkdownViewer from '../components/MarkdownViewer.vue'
import { useChapters } from '../composables/useChapters'

const props = defineProps({
  id: { type: String, required: true },
})

const router = useRouter()
const { getChapter, getAdjacent } = useChapters()

const chapter = computed(() => getChapter(props.id))
const adjacent = computed(() => getAdjacent(props.id))
</script>

<template>
  <div v-if="chapter" class="chapter-page">
    <header class="chapter-header">
      <p class="chapter-label">Chapter {{ chapter.number }}</p>
      <h1>{{ chapter.title }}</h1>
    </header>

    <MarkdownViewer :chapter="chapter" />

    <nav class="chapter-nav">
      <n-button
        v-if="adjacent.prev"
        quaternary
        @click="router.push({ name: 'chapter', params: { id: adjacent.prev.id } })"
      >
        <template #icon>
          <n-icon><ArrowBackOutline /></n-icon>
        </template>
        Ch. {{ adjacent.prev.number }}
      </n-button>
      <span v-else />

      <n-button
        v-if="adjacent.next"
        type="primary"
        @click="router.push({ name: 'chapter', params: { id: adjacent.next.id } })"
      >
        Ch. {{ adjacent.next.number }}
        <template #icon>
          <n-icon><ArrowForwardOutline /></n-icon>
        </template>
      </n-button>
    </nav>
  </div>

  <n-result
    v-else
    status="404"
    title="Chapter not found"
    description="That chapter doesn't exist in this guide."
  >
    <template #footer>
      <n-button @click="router.push('/')">Back to home</n-button>
    </template>
  </n-result>
</template>

<style scoped>
.chapter-page {
  max-width: 820px;
}

.chapter-header {
  margin-bottom: 2rem;
  padding-bottom: 1.25rem;
  border-bottom: 1px solid var(--border-color);
}

.chapter-label {
  margin: 0 0 0.35rem;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--accent);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.chapter-header h1 {
  margin: 0;
  font-size: 1.75rem;
  line-height: 1.3;
}

.chapter-nav {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 3rem;
  padding-top: 1.5rem;
  border-top: 1px solid var(--border-color);
}
</style>
