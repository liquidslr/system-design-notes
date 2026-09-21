<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { authState, hasRole, logout } from './auth'

const router = useRouter()
const menuOpen = ref(false)
const menuEl = ref(null)

function onDocClick(e) {
  if (menuEl.value && !menuEl.value.contains(e.target)) menuOpen.value = false
}
onMounted(() => document.addEventListener('click', onDocClick))
onUnmounted(() => document.removeEventListener('click', onDocClick))

async function signOut() {
  menuOpen.value = false
  await logout()
  router.push('/')
}

function go(path) {
  menuOpen.value = false
  router.push(path)
}
</script>

<template>
  <div class="app">
    <nav class="navbar">
      <RouterLink to="/" class="logo"><span class="play">▶</span> MyTube</RouterLink>

      <div class="nav-actions">
        <RouterLink v-if="hasRole('creator')" to="/upload" class="btn">Upload</RouterLink>

        <template v-if="authState.user">
          <div ref="menuEl" class="user-menu">
            <button class="user-btn" @click="menuOpen = !menuOpen">
              {{ authState.user.username }}<span class="caret">▾</span>
            </button>
            <div v-if="menuOpen" class="dropdown">
              <div class="dropdown-header">
                <div class="name">{{ authState.user.username }}</div>
                <div class="mail">{{ authState.user.email }}</div>
                <span class="role-tag" :class="authState.user.role">
                  {{ authState.user.role }}
                </span>
              </div>
              <button class="dropdown-item" @click="go('/my-videos')">My videos</button>
              <button v-if="hasRole('admin')" class="dropdown-item" @click="go('/admin/users')">
                Admin panel
              </button>
              <button v-if="hasRole('moderator')" class="dropdown-item" @click="go('/moderation')">
                Moderation
              </button>
              <button class="dropdown-item" @click="signOut">Sign out</button>
            </div>
          </div>
        </template>

        <template v-else-if="authState.ready">
          <RouterLink to="/login" class="btn secondary">Login</RouterLink>
          <RouterLink to="/register" class="btn">Register</RouterLink>
        </template>
      </div>
    </nav>

    <main class="content">
      <RouterView />
    </main>
  </div>
</template>
