<script setup>
import { computed, onMounted, ref } from 'vue'
import { banUser, extractError, listUsers, setUserRole, unbanUser } from '../api'
import { authState } from '../auth'

const PAGE_SIZE = 50
const ROLES = ['user', 'creator', 'moderator', 'admin']

const users = ref([])
const total = ref(0)
const error = ref('')
const notice = ref('')
const loading = ref(false)
const busyId = ref('')

const canLoadMore = computed(() => users.value.length < total.value)
const myId = computed(() => authState.user?.id)

function fmtDate(ts) {
  return ts ? new Date(ts * 1000).toLocaleDateString() : ''
}

async function load(reset = false) {
  loading.value = true
  error.value = ''
  try {
    const offset = reset ? 0 : users.value.length
    const { data } = await listUsers(PAGE_SIZE, offset)
    total.value = data.total
    users.value = reset ? data.users : users.value.concat(data.users)
  } catch (e) {
    error.value = extractError(e, 'Could not load users')
  } finally {
    loading.value = false
  }
}

async function changeRole(user, role) {
  busyId.value = user.id
  error.value = ''
  notice.value = ''
  try {
    const { data } = await setUserRole(user.id, role)
    user.role = data.role
    // The new role lands in that user's NEXT access token, not the current one.
    notice.value = `${user.username} is now ${role}. They must sign in again for it to take effect.`
  } catch (e) {
    error.value = extractError(e, 'Could not change role')
    await load(true)   // roll the select back to server truth
  } finally {
    busyId.value = ''
  }
}

async function toggleBan(user) {
  busyId.value = user.id
  error.value = ''
  notice.value = ''
  try {
    const banning = user.status === 'active'
    const { data } = banning
      ? await banUser(user.id, 'banned by admin')
      : await unbanUser(user.id)
    user.status = data.status
    notice.value = banning
      ? `${user.username} was banned; their sessions were revoked.`
      : `${user.username} was unbanned.`
  } catch (e) {
    error.value = extractError(e, 'Operation failed')
  } finally {
    busyId.value = ''
  }
}

onMounted(() => load(true))
</script>

<template>
  <div>
    <h2 style="margin-top: 0">
      Users <small style="color: var(--text-dim)">({{ total }})</small>
    </h2>

    <div v-if="error" class="error-box">{{ error }}</div>
    <div v-if="notice" class="hint-box">{{ notice }}</div>

    <div class="table-wrap">
      <table class="users">
        <thead>
          <tr>
            <th>Username</th>
            <th>Email</th>
            <th>Role</th>
            <th>Status</th>
            <th>Registered</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in users" :key="u.id">
            <td>
              {{ u.username }}
              <span v-if="u.id === myId" style="color: var(--text-dim)">(you)</span>
            </td>
            <td style="color: var(--text-dim)">{{ u.email }}</td>
            <td>
              <select
                :value="u.role"
                :disabled="u.id === myId || busyId === u.id"
                @change="changeRole(u, $event.target.value)"
              >
                <option v-for="r in ROLES" :key="r" :value="r">{{ r }}</option>
              </select>
            </td>
            <td>
              <span class="badge" :class="u.status === 'banned' ? 'failed' : 'ready'">
                {{ u.status }}
              </span>
            </td>
            <td style="color: var(--text-dim)">{{ fmtDate(u.created_at) }}</td>
            <td>
              <div class="row-actions">
                <button
                  class="btn tiny"
                  :class="{ danger: u.status === 'active' }"
                  :disabled="u.id === myId || busyId === u.id"
                  @click="toggleBan(u)"
                >
                  {{ u.status === 'active' ? 'Ban' : 'Unban' }}
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p v-if="!users.length && !loading" class="empty-state">No users found.</p>

    <button
      v-if="canLoadMore"
      class="btn secondary"
      style="margin-top: 16px"
      :disabled="loading"
      @click="load()"
    >
      {{ loading ? 'Loading…' : `Load more (${users.length}/${total})` }}
    </button>
  </div>
</template>
