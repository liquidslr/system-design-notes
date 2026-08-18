<script setup>
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { NLayout, NLayoutSider, NLayoutContent, NLayoutHeader, NButton, NIcon } from 'naive-ui'
import { MenuOutline, MoonOutline, SunnyOutline } from '@vicons/ionicons5'
import AppSidebar from './components/AppSidebar.vue'

const route = useRoute()
const collapsed = ref(false)
const isDark = ref(false)

const pageTitle = computed(() => {
  if (route.name === 'home') return 'Home'
  if (route.name === 'chapter') return `Chapter`
  return 'System Design Notes'
})

function toggleTheme() {
  isDark.value = !isDark.value
  document.documentElement.setAttribute('data-theme', isDark.value ? 'dark' : 'light')
}
</script>

<template>
  <n-layout has-sider class="app-layout">
    <n-layout-sider
      bordered
      collapse-mode="width"
      :collapsed-width="0"
      :width="280"
      :collapsed="collapsed"
      show-trigger="bar"
      @collapse="collapsed = true"
      @expand="collapsed = false"
      class="app-sider"
    >
      <AppSidebar />
    </n-layout-sider>

    <n-layout>
      <n-layout-header bordered class="app-header">
        <n-button quaternary circle @click="collapsed = !collapsed" class="menu-btn">
          <template #icon>
            <n-icon><MenuOutline /></n-icon>
          </template>
        </n-button>
        <span class="header-title">{{ pageTitle }}</span>
        <n-button quaternary circle @click="toggleTheme" class="theme-btn">
          <template #icon>
            <n-icon><component :is="isDark ? SunnyOutline : MoonOutline" /></n-icon>
          </template>
        </n-button>
      </n-layout-header>

      <n-layout-content class="app-content">
        <router-view />
      </n-layout-content>
    </n-layout>
  </n-layout>
</template>

<style scoped>
.app-layout {
  min-height: 100vh;
}

.app-sider {
  background: var(--sidebar-bg) !important;
}

.app-header {
  height: 56px;
  display: flex;
  align-items: center;
  padding: 0 1rem;
  gap: 0.75rem;
  background: var(--header-bg);
}

.header-title {
  flex: 1;
  font-weight: 600;
  color: var(--text-primary);
}

.app-content {
  padding: 1.5rem 2rem 3rem;
  background: var(--content-bg);
  min-height: calc(100vh - 56px);
}

@media (max-width: 768px) {
  .app-content {
    padding: 1rem;
  }
}
</style>
