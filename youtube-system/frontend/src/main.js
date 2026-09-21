import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import { setAuthFailureHandler } from './api'
import { restore } from './auth'
import './style.css'

// Session expired mid-use: send the user to the login page and remember where
// they were. Injected here (not inside api.js) to keep imports one-directional.
setAuthFailureHandler((path) => {
  router.push({
    path: '/login',
    query: path && path !== '/' ? { redirect: path } : {},
  })
})

// Restore the session before mounting so a page refresh never flashes the
// logged-out navbar. Costs one /api/auth/me round trip on first paint.
restore().finally(() => {
  createApp(App).use(router).mount('#app')
})
