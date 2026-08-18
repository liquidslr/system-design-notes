import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import ChapterView from '../views/ChapterView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', name: 'home', component: HomeView },
    { path: '/chapter/:id', name: 'chapter', component: ChapterView, props: true },
  ],
  scrollBehavior() {
    return { top: 0 }
  },
})

export default router
