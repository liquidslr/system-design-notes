<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { extractError } from '../api'
import { login } from '../auth'

const route = useRoute()
const router = useRouter()
const email = ref('')
const password = ref('')
const error = ref('')
const busy = ref(false)

async function submit() {
  error.value = ''
  if (!email.value.trim() || !password.value) {
    error.value = 'Email and password are required'
    return
  }
  busy.value = true
  try {
    await login(email.value.trim(), password.value)
    // Honour ?redirect= so the guard sends users back where they came from.
    const redirect = route.query.redirect
    router.push(typeof redirect === 'string' && redirect.startsWith('/') ? redirect : '/')
  } catch (e) {
    error.value = extractError(e, 'Login failed')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-card">
      <h2>Sign in to MyTube</h2>

      <div class="field">
        <label>Email</label>
        <input
          v-model="email"
          type="email"
          placeholder="you@example.com"
          autocomplete="username"
          @keyup.enter="submit"
        />
      </div>

      <div class="field">
        <label>Password</label>
        <input
          v-model="password"
          type="password"
          placeholder="Your password"
          autocomplete="current-password"
          @keyup.enter="submit"
        />
      </div>

      <div v-if="error" class="error-box">{{ error }}</div>

      <button class="btn" style="width: 100%" :disabled="busy" @click="submit">
        {{ busy ? 'Signing in…' : 'Sign in' }}
      </button>

      <p class="auth-footer">
        No account? <RouterLink to="/register">Register</RouterLink>
      </p>
      <p class="auth-footer">
        Local test accounts: <code>admin@mytube.local / Admin@123</code> ·
        <code>creator@mytube.local / Creator@123</code>
      </p>
    </div>
  </div>
</template>
