import { reactive } from 'vue'
import { loginRequest, logoutRequest, meRequest, registerRequest } from './api'
import { clearTokens, getAccess, getRefresh, setTokens } from './tokens'

// Re-exported so views can import everything auth-related from one place
// (spec 5.1 lists these as auth.js exports).
export { clearTokens, getAccess, getRefresh, setTokens }

/** Must stay in sync with ROLE_LEVEL in app/auth/security.py (spec 1.3). */
export const ROLE_LEVEL = { user: 1, creator: 2, moderator: 3, admin: 4 }

export const authState = reactive({ user: null, ready: false })

export function hasRole(minRole) {
  const user = authState.user
  if (!user) return false
  return (ROLE_LEVEL[user.role] || 0) >= (ROLE_LEVEL[minRole] || 0)
}

/**
 * Rebuild the session on page load. An expired access token is transparently
 * renewed by the api.js interceptor, so this only fails when the refresh token
 * is gone too.
 */
export async function restore() {
  if (!getAccess()) {
    authState.ready = true
    return
  }
  try {
    const { data } = await meRequest()
    authState.user = data
  } catch {
    clearTokens()
    authState.user = null
  } finally {
    authState.ready = true
  }
}

export async function login(email, password) {
  const { data } = await loginRequest(email, password)
  setTokens(data.access_token, data.refresh_token)
  authState.user = data.user
  return data
}

/**
 * The register endpoint deliberately returns no tokens, so log in immediately
 * with the same credentials: RegisterView can treat success as "logged in".
 */
export async function register(username, email, password) {
  const { data } = await registerRequest(username, email, password)
  await login(email, password)
  return data.user
}

export async function logout() {
  try {
    await logoutRequest()
  } catch {
    // Token may already be expired - clearing locally is what matters.
  }
  clearTokens()
  authState.user = null
}
