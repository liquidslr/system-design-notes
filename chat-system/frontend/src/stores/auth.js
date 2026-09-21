import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

const API_BASE = '/api'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('token') || '')
  const user = ref(null)

  const isLoggedIn = computed(() => !!token.value)

  function setToken(newToken) {
    token.value = newToken
    localStorage.setItem('token', newToken)
    axios.defaults.headers.common['Authorization'] = `Bearer ${newToken}`
  }

  function clearToken() {
    token.value = ''
    user.value = null
    localStorage.removeItem('token')
    delete axios.defaults.headers.common['Authorization']
  }

  async function login(username, password) {
    const res = await axios.post(`${API_BASE}/auth/login`, { username, password })
    setToken(res.data.access_token)
    await fetchProfile()
  }

  async function register(username, email, password, nickname) {
    await axios.post(`${API_BASE}/auth/register`, { username, email, password, nickname })
    await login(username, password)
  }

  async function fetchProfile() {
    try {
      const res = await axios.get(`${API_BASE}/users/me`)
      user.value = res.data
    } catch {
      clearToken()
    }
  }

  function logout() {
    clearToken()
  }

  // Initialize axios default header if token exists
  if (token.value) {
    axios.defaults.headers.common['Authorization'] = `Bearer ${token.value}`
  }

  return { token, user, isLoggedIn, login, register, fetchProfile, logout, clearToken }
})
