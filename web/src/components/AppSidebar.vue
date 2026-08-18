<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NMenu } from 'naive-ui'
import { useChapters } from '../composables/useChapters'

const route = useRoute()
const router = useRouter()
const { chapters } = useChapters()

const activeKey = computed(() => (route.name === 'chapter' ? route.params.id : null))

const options = computed(() =>
  chapters.map((chapter) => ({
    label: `Ch. ${chapter.number}: ${chapter.title.replace(/^Chapter \d+:\s*/i, '')}`,
    key: chapter.id,
  }))
)

function handleSelect(key) {
  router.push({ name: 'chapter', params: { id: key } })
}
</script>

<template>
  <nav class="sidebar">
    <div class="sidebar-header">
      <router-link to="/" class="brand">System Design Notes</router-link>
      <p class="sidebar-subtitle">{{ chapters.length }} chapters</p>
    </div>
    <n-menu
      :value="activeKey"
      :options="options"
      @update:value="handleSelect"
    />
  </nav>
</template>

<style scoped>
.sidebar {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--sidebar-bg);
}

.sidebar-header {
  padding: 1.25rem 1rem 0.75rem;
  border-bottom: 1px solid var(--border-color);
}

.brand {
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--text-primary);
  text-decoration: none;
  line-height: 1.3;
}

.brand:hover {
  color: var(--accent);
}

.sidebar-subtitle {
  margin: 0.35rem 0 0;
  font-size: 0.8rem;
  color: var(--text-muted);
}
</style>
