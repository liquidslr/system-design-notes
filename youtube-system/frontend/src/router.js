import { createRouter, createWebHistory } from 'vue-router'
import { authState, hasRole } from './auth'
import AdminUsersView from './views/AdminUsersView.vue'
import HomeView from './views/HomeView.vue'
import LoginView from './views/LoginView.vue'
import ModerationView from './views/ModerationView.vue'
import MyVideosView from './views/MyVideosView.vue'
import RegisterView from './views/RegisterView.vue'
import UploadView from './views/UploadView.vue'
import WatchView from './views/WatchView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: HomeView },
    { path: '/login', component: LoginView, meta: { guestOnly: true } },
    { path: '/register', component: RegisterView, meta: { guestOnly: true } },
    {
      path: '/upload',
      component: UploadView,
      // No hard redirect on insufficient role: UploadView renders an inline
      // "requires creator role" message instead (spec 5.3).
      meta: { requiresAuth: true, role: 'creator' },
    },
    { path: '/my-videos', component: MyVideosView, meta: { requiresAuth: true } },
    {
      path: '/admin/users',
      component: AdminUsersView,
      meta: { requiresAuth: true, role: 'admin' },
    },
    {
      path: '/moderation',
      component: ModerationView,
      meta: { requiresAuth: true, role: 'moderator' },
    },
    { path: '/watch/:id', component: WatchView },
  ],
})

router.beforeEach((to) => {
  const loggedIn = !!authState.user

  if (to.meta.guestOnly && loggedIn) return { path: '/' }

  if (to.meta.requiresAuth && !loggedIn) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  // Insufficient role: bounce home for the admin panel (do not advertise that
  // it exists), but let /upload through so it can explain itself inline.
  if (to.meta.role && loggedIn && !hasRole(to.meta.role) && to.path !== '/upload') {
    return { path: '/' }
  }

  return true
})

export default router
