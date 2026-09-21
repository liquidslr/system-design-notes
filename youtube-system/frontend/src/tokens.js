/**
 * Raw localStorage access for the two tokens.
 *
 * Split out from auth.js so api.js (whose interceptors must read and clear
 * tokens) never has to import auth.js - that would be a circular import.
 */
const ACCESS_KEY = 'mytube_access'
const REFRESH_KEY = 'mytube_refresh'

export function getAccess() {
  return localStorage.getItem(ACCESS_KEY)
}

export function getRefresh() {
  return localStorage.getItem(REFRESH_KEY)
}

export function setTokens(access, refresh) {
  localStorage.setItem(ACCESS_KEY, access)
  localStorage.setItem(REFRESH_KEY, refresh)
}

export function clearTokens() {
  localStorage.removeItem(ACCESS_KEY)
  localStorage.removeItem(REFRESH_KEY)
}
