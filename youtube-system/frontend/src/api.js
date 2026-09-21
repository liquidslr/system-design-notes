import axios from 'axios'
import { clearTokens, getAccess, getRefresh, setTokens } from './tokens'

const http = axios.create({ baseURL: '', timeout: 0 })

/**
 * Session-failure hook, installed by main.js. Kept as an injected callback so
 * this module does not have to import the router (which imports auth -> api).
 */
let authFailureHandler = null
export function setAuthFailureHandler(fn) {
  authFailureHandler = fn
}

/** Uniform error text extraction: FastAPI puts the message in `detail`. */
export function extractError(e, fallback = 'Request failed') {
  return e?.response?.data?.detail || e?.message || fallback
}

// ---- request: attach the bearer token when we have one ----
http.interceptors.request.use((cfg) => {
  const token = getAccess()
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

// ---- response: single-flight refresh on 401, then replay the request once ----
let refreshing = null

function isAuthCall(cfg) {
  const url = cfg?.url || ''
  return url.includes('/api/auth/login') || url.includes('/api/auth/refresh')
}

function pathOf(cfg) {
  const url = cfg?.url || '/'
  return url.startsWith('/') ? url.split('?')[0] : '/'
}

async function doRefresh() {
  // Bare axios, NOT `http`: going through the instance would recurse into this
  // very interceptor when the refresh itself returns 401.
  const { data } = await axios.post('/api/auth/refresh', {
    refresh_token: getRefresh(),
  })
  setTokens(data.access_token, data.refresh_token)
  return data
}

http.interceptors.response.use(
  (res) => res,
  async (error) => {
    const cfg = error.config
    const status = error.response?.status
    if (status !== 401 || !cfg || cfg._retried || isAuthCall(cfg) || !getRefresh()) {
      return Promise.reject(error)
    }
    cfg._retried = true
    try {
      // Shared promise: concurrent 401s must not each rotate the token, since
      // rotation invalidates the previous one and they would revoke each other.
      refreshing = refreshing || doRefresh()
      await refreshing
      refreshing = null
      return await http.request(cfg)
    } catch (refreshError) {
      refreshing = null
      clearTokens()
      if (authFailureHandler) authFailureHandler(pathOf(cfg))
      return Promise.reject(refreshError)
    }
  },
)

// ---- auth ----
export function registerRequest(username, email, password) {
  return http.post('/api/auth/register', { username, email, password })
}

export function loginRequest(email, password) {
  return http.post('/api/auth/login', { email, password })
}

export function meRequest() {
  return http.get('/api/auth/me')
}

export function logoutRequest() {
  return http.post('/api/auth/logout')
}

// ---- users (admin) ----
export function listUsers(limit = 50, offset = 0) {
  return http.get('/api/users', { params: { limit, offset } })
}

export function setUserRole(id, role) {
  return http.patch(`/api/users/${id}/role`, { role })
}

export function banUser(id, reason = '') {
  return http.post(`/api/users/${id}/ban`, { reason })
}

export function unbanUser(id) {
  return http.post(`/api/users/${id}/unban`)
}

// ---- videos ----
export function getUploadUrl(filename, size, contentType = 'video/mp4') {
  return http.post('/api/upload-url', {
    filename,
    size,
    content_type: contentType,
  })
}

export function uploadBinary(uploadPath, file, onProgress) {
  return http.post(`${uploadPath}?filename=${encodeURIComponent(file.name)}`, file, {
    headers: { 'Content-Type': 'application/octet-stream' },
    onUploadProgress: (e) => onProgress && onProgress(e),
  })
}

export function createVideo(videoId, title, description, filename) {
  return http.post('/api/videos', {
    video_id: videoId,
    title,
    description,
    filename,
  })
}

export function listVideos() {
  return http.get('/api/videos')
}

export function listMyVideos() {
  return http.get('/api/videos/mine')
}

export function getVideo(id) {
  return http.get(`/api/videos/${id}`)
}

export function retryVideo(id) {
  return http.post(`/api/videos/${id}/retry`)
}

export function getStats() {
  return http.get('/api/stats')
}

// ---- comments & votes ----
export function listComments(videoId, { sort = 'top', limit = 20, offset = 0 } = {}) {
  return http.get(`/api/videos/${videoId}/comments`, { params: { sort, limit, offset } })
}

export function listReplies(commentId, { limit = 20, offset = 0 } = {}) {
  return http.get(`/api/comments/${commentId}/replies`, { params: { limit, offset } })
}

export function createComment(videoId, content, replyTo = null) {
  return http.post(`/api/videos/${videoId}/comments`, { content, reply_to: replyTo })
}

export function deleteComment(commentId) {
  return http.delete(`/api/comments/${commentId}`)
}

export function voteComment(commentId, value) {
  return http.put(`/api/comments/${commentId}/vote`, { value })
}

// ---- moderation ----
export function listModerationQueue(limit = 50, offset = 0) {
  return http.get('/api/moderation/queue', { params: { limit, offset } })
}

export function approveVideo(videoId) {
  return http.post(`/api/moderation/${videoId}/approve`)
}

export function rejectVideo(videoId, reason) {
  return http.post(`/api/moderation/${videoId}/reject`, { reason })
}

export function resubmitVideo(videoId, title, description) {
  return http.post(`/api/videos/${videoId}/resubmit`, { title, description })
}
