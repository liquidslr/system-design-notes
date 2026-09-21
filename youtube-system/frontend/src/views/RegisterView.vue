<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { extractError } from '../api'
import { register } from '../auth'

const router = useRouter()
const username = ref('')
const email = ref('')
const password = ref('')
const confirm = ref('')
const error = ref('')
const busy = ref(false)

// Mirror the backend rules (spec 4.4) so users get feedback before a round trip.
const usernameHint = computed(() => {
  const v = username.value
  if (!v) return ''
  if (v.length < 3 || v.length > 32) return 'Username must be 3-32 characters'
  if (!/^[a-zA-Z0-9_]+$/.test(v)) return 'Only letters, digits and underscore'
  return ''
})
const passwordHint = computed(() => {
  if (!password.value) return ''
  if (password.value.length < 8) return 'At least 8 characters'
  if (password.value.length > 72) return 'At most 72 characters'
  return ''
})
const mismatch = computed(() => !!confirm.value && confirm.value !== password.value)
const canSubmit = computed(() =>
  !!username.value && !!email.value && !!password.value &&
  !usernameHint.value && !passwordHint.value && !mismatch.value)

async function submit() {
  error.value = ''
  if (!canSubmit.value) {
    error.value = mismatch.value ? 'Passwords do not match' : 'Please fix the fields above'
    return
  }
  busy.value = true
  try {
    // register() logs in automatically, so we land on the home page signed in.
    await register(username.value.trim(), email.value.trim().toLowerCase(), password.value)
    router.push('/')
  } catch (e) {
    error.value = extractError(e, 'Registration failed')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-card">
      <h2>Create your account</h2>

      <div class="field">
        <label>Username</label>
        <input v-model="username" placeholder="alice_01" autocomplete="username" />
        <small v-if="usernameHint" style="color: var(--accent)">{{ usernameHint }}</small>
      </div>

      <div class="field">
        <label>Email</label>
        <input v-model="email" type="email" placeholder="you@example.com" />
      </div>

      <div class="field">
        <label>Password</label>
        <input v-model="password" type="password" placeholder="At least 8 characters"
               autocomplete="new-password" />
        <small v-if="passwordHint" style="color: var(--accent)">{{ passwordHint }}</small>
      </div>

      <div class="field">
        <label>Confirm password</label>
        <input v-model="confirm" type="password" autocomplete="new-password"
               @keyup.enter="submit" />
        <small v-if="mismatch" style="color: var(--accent)">Passwords do not match</small>
      </div>

      <div v-if="error" class="error-box">{{ error }}</div>

      <button class="btn" style="width: 100%" :disabled="busy || !canSubmit" @click="submit">
        {{ busy ? 'Creating…' : 'Register' }}
      </button>

      <p class="auth-footer">
        Already have an account? <RouterLink to="/login">Sign in</RouterLink>
      </p>
      <p class="auth-footer" style="font-size: 12px">
        New accounts get the <span class="role-tag">user</span> role and cannot upload
        until an admin promotes them to <span class="role-tag creator">creator</span>.
      </p>
    </div>
  </div>
</template>
