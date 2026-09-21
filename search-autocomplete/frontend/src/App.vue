<template>
  <div id="app">
    <header class="app-header">
      <h1>Search Autocomplete</h1>
      <p class="subtitle">Trie-based real-time suggestions with top-k caching</p>
    </header>
    <main class="app-main">
      <SearchBox />
    </main>
    <footer class="app-footer">
      <a href="/api/stats" target="_blank">System Stats</a>
      <span>·</span>
      <a href="/api/suggestions?prefix=tw" target="_blank">API Demo: "tw"</a>
    </footer>
  </div>
</template>

<script setup>
import SearchBox from './components/SearchBox.vue'
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  min-height: 100vh;
  color: #333;
}

#app {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-height: 100vh;
  padding: 2rem 1rem;
}

.app-header {
  text-align: center;
  margin-bottom: 2rem;
}

.app-header h1 {
  font-size: 2.2rem;
  color: white;
  font-weight: 700;
  text-shadow: 0 2px 4px rgba(0,0,0,0.2);
}

.subtitle {
  color: rgba(255,255,255,0.85);
  font-size: 1rem;
  margin-top: 0.5rem;
}

.app-main {
  width: 100%;
  max-width: 640px;
  flex: 1;
}

.app-footer {
  margin-top: 2rem;
  display: flex;
  gap: 0.75rem;
  align-items: center;
}

.app-footer a {
  color: rgba(255,255,255,0.8);
  text-decoration: none;
  font-size: 0.85rem;
  transition: color 0.2s;
}

.app-footer a:hover {
  color: white;
}

.app-footer span {
  color: rgba(255,255,255,0.4);
}
</style>
