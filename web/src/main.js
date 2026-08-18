import { createApp } from 'vue'
import naive from 'naive-ui'
import router from './router'
import './style.css'
import 'highlight.js/styles/github.css'
import App from './App.vue'

createApp(App).use(naive).use(router).mount('#app')
