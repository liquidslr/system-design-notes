import { useAuthStore } from '../stores/auth'

export function useAuth() {
  const authStore = useAuthStore()

  return {
    login: authStore.login,
    register: authStore.register,
    logout: authStore.logout,
    user: authStore.user,
    isLoggedIn: authStore.isLoggedIn,
  }
}
