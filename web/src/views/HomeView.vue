<script setup>
import { computed } from 'vue'
import { NCard, NGrid, NGridItem, NTag } from 'naive-ui'
import { useChapters } from '../composables/useChapters'

const { manifest, chapters } = useChapters()

const grouped = computed(() => {
  const vol1 = chapters.filter((c) => c.number <= 16)
  const vol2 = chapters.filter((c) => c.number > 16)
  return { vol1, vol2 }
})
</script>

<template>
  <div class="home">
    <header class="hero">
      <h1>{{ manifest.title }}</h1>
      <p class="lead">{{ manifest.subtitle }}</p>
      <p class="meta">
        Based on
        <a href="https://bytebytego.com/courses/system-design-interview" target="_blank" rel="noopener">
          System Design Interview by Alex Xu
        </a>
        ·
        <a :href="manifest.source" target="_blank" rel="noopener">Source repository</a>
      </p>
    </header>

    <section class="volume">
      <h2>Volume 1 <n-tag size="small" round>{{ grouped.vol1.length }} chapters</n-tag></h2>
      <n-grid cols="1 s:2 m:3" responsive="screen" :x-gap="16" :y-gap="16">
        <n-grid-item v-for="chapter in grouped.vol1" :key="chapter.id">
          <router-link :to="{ name: 'chapter', params: { id: chapter.id } }" class="card-link">
            <n-card hoverable>
              <template #header>
                <span class="chapter-num">Chapter {{ chapter.number }}</span>
              </template>
              {{ chapter.title.replace(/^Chapter \d+:\s*/i, '') }}
            </n-card>
          </router-link>
        </n-grid-item>
      </n-grid>
    </section>

    <section class="volume">
      <h2>Volume 2 <n-tag size="small" round>{{ grouped.vol2.length }} chapters</n-tag></h2>
      <n-grid cols="1 s:2 m:3" responsive="screen" :x-gap="16" :y-gap="16">
        <n-grid-item v-for="chapter in grouped.vol2" :key="chapter.id">
          <router-link :to="{ name: 'chapter', params: { id: chapter.id } }" class="card-link">
            <n-card hoverable>
              <template #header>
                <span class="chapter-num">Chapter {{ chapter.number }}</span>
              </template>
              {{ chapter.title.replace(/^Chapter \d+:\s*/i, '') }}
            </n-card>
          </router-link>
        </n-grid-item>
      </n-grid>
    </section>
  </div>
</template>

<style scoped>
.home {
  max-width: 960px;
}

.hero {
  margin-bottom: 2.5rem;
}

.hero h1 {
  margin: 0 0 0.75rem;
  font-size: 2rem;
  line-height: 1.2;
}

.lead {
  margin: 0 0 0.75rem;
  font-size: 1.05rem;
  color: var(--text-secondary);
  line-height: 1.6;
}

.meta {
  margin: 0;
  font-size: 0.9rem;
  color: var(--text-muted);
}

.meta a {
  color: var(--accent);
}

.volume {
  margin-bottom: 2.5rem;
}

.volume h2 {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0 0 1rem;
  font-size: 1.25rem;
}

.card-link {
  text-decoration: none;
  color: inherit;
  display: block;
}

.chapter-num {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--accent);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
</style>
