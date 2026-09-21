<template>
  <div class="profile-container">
    <div class="profile-card">
      <button @click="$router.push('/')" class="back-btn">&larr; Back to Chat</button>
      <h2>Profile</h2>

      <div class="avatar">
        <div class="avatar-circle">{{ initials }}</div>
      </div>

      <form @submit.prevent="updateProfile">
        <div class="form-group">
          <label>Username</label>
          <input :value="authStore.user?.username" disabled />
        </div>
        <div class="form-group">
          <label>Email</label>
          <input :value="authStore.user?.email" disabled />
        </div>
        <div class="form-group">
          <label>Nickname</label>
          <input v-model="nickname" placeholder="Your nickname" />
        </div>

        <button type="submit" class="save-btn">Save Changes</button>
      </form>

      <button @click="handleLogout" class="logout-btn">Logout</button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import axios from 'axios'

const router = useRouter()
const authStore = useAuthStore()
const nickname = ref('')

const initials = computed(() => {
  const name = authStore.user?.nickname || authStore.user?.username || '?'
  return name.charAt(0).toUpperCase()
})

async function updateProfile() {
  try {
    await axios.put('/api/users/me', { nickname: nickname.value })
    await authStore.fetchProfile()
    alert('Profile updated!')
  } catch (e) {
    alert('Failed to update profile')
  }
}

function handleLogout() {
  authStore.logout()
  router.push('/login')
}

onMounted(() => {
  nickname.value = authStore.user?.nickname || ''
})
</script>

<style scoped>
.profile-container {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100vh;
  background: #f0f2f5;
}

.profile-card {
  background: white;
  padding: 2rem;
  border-radius: 12px;
  box-shadow: 0 4px 20px rgba(0,0,0,0.1);
  width: 400px;
  text-align: center;
}

.back-btn {
  background: none;
  border: none;
  color: #667eea;
  cursor: pointer;
  font-size: 0.9rem;
  margin-bottom: 1rem;
}

.avatar-circle {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  background: linear-gradient(135deg, #667eea, #764ba2);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 2rem;
  margin: 1rem auto;
}

.form-group {
  margin-bottom: 1rem;
  text-align: left;
}

.form-group label {
  display: block;
  font-size: 0.85rem;
  color: #666;
  margin-bottom: 0.25rem;
}

.form-group input {
  width: 100%;
  padding: 0.5rem;
  border: 1px solid #ddd;
  border-radius: 6px;
  outline: none;
}

.form-group input:disabled {
  background: #f5f5f5;
  color: #999;
}

.save-btn {
  width: 100%;
  padding: 0.75rem;
  background: #667eea;
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  margin-top: 0.5rem;
}

.logout-btn {
  width: 100%;
  padding: 0.75rem;
  background: #e74c3c;
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  margin-top: 1rem;
}
</style>
