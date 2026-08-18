<script setup>
import { ref, watch } from 'vue'
import { NSpin, NAlert } from 'naive-ui'
import { useMarkdown } from '../composables/useMarkdown'

const props = defineProps({
  chapter: { type: Object, required: true },
})

const { render } = useMarkdown()
const html = ref('')
const loading = ref(true)
const error = ref(null)

async function loadContent() {
  loading.value = true
  error.value = null
  html.value = ''

  try {
    const readme = props.chapter.readme
    const url = `/content/${props.chapter.id}/${readme}`
    const response = await fetch(url)
    if (!response.ok) throw new Error(`Failed to load chapter (${response.status})`)
    const markdown = await response.text()
    const basePath = `/content/${props.chapter.id}`
    html.value = render(markdown, basePath)
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

watch(() => props.chapter.id, loadContent, { immediate: true })
</script>

<template>
  <div class="markdown-viewer">
    <n-spin v-if="loading" size="large" />
    <n-alert v-else-if="error" type="error" :title="error" />
    <article v-else class="markdown-body" v-html="html" />
  </div>
</template>

<style scoped>
.markdown-viewer {
  min-height: 200px;
}
</style>
