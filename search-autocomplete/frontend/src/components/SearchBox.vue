<template>
  <div class="search-container">
    <div class="search-box" :class="{ focused: isFocused }">
      <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="11" cy="11" r="8" />
        <path d="M21 21l-4.35-4.35" />
      </svg>
      <input
        ref="inputRef"
        v-model="query"
        type="text"
        placeholder="Search anything..."
        class="search-input"
        @focus="onFocus"
        @blur="onBlur"
        @keydown="onKeydown"
        @input="onInput"
      />
      <button v-if="query" class="clear-btn" @mousedown.prevent="clearQuery">
        &times;
      </button>
    </div>

    <!-- Suggestions Dropdown -->
    <div v-if="showSuggestions" class="suggestions">
      <div v-if="loading" class="suggestion-item loading">
        <span class="loading-dots">Loading...</span>
      </div>
      <div v-else-if="suggestions.length === 0 && query.length > 0" class="suggestion-item empty">
        No suggestions found
      </div>
      <div
        v-else
        v-for="(suggestion, index) in suggestions"
        :key="suggestion.query"
        class="suggestion-item"
        :class="{ active: selectedIndex === index }"
        @mousedown.prevent="selectSuggestion(suggestion)"
        @mouseenter="selectedIndex = index"
      >
        <div class="suggestion-content">
          <span class="suggestion-text" v-html="highlightMatch(suggestion.query)"></span>
          <div class="frequency-bar">
            <div
              class="frequency-fill"
              :style="{ width: getFrequencyWidth(suggestion.frequency) + '%' }"
            ></div>
          </div>
        </div>
        <span class="frequency-count">{{ formatFrequency(suggestion.frequency) }}</span>
      </div>
    </div>

    <!-- Search Result -->
    <div v-if="searchedQuery" class="search-result">
      <p>You searched for: <strong>{{ searchedQuery }}</strong></p>
      <p class="result-note">Query recorded for future aggregation</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import axios from 'axios'

const API_BASE = '/api'

const query = ref('')
const suggestions = ref([])
const loading = ref(false)
const isFocused = ref(false)
const selectedIndex = ref(-1)
const searchedQuery = ref('')
const inputRef = ref(null)

let debounceTimer = null
const DEBOUNCE_MS = 300

const showSuggestions = computed(() => {
  return isFocused.value && query.value.length > 0
})

function onInput() {
  selectedIndex.value = -1
  searchedQuery.value = ''

  if (debounceTimer) clearTimeout(debounceTimer)

  if (!query.value.trim()) {
    suggestions.value = []
    loading.value = false
    return
  }

  loading.value = true
  debounceTimer = setTimeout(fetchSuggestions, DEBOUNCE_MS)
}

async function fetchSuggestions() {
  if (!query.value.trim()) return

  try {
    const res = await axios.get(`${API_BASE}/suggestions`, {
      params: { prefix: query.value.trim() }
    })
    suggestions.value = res.data.suggestions
  } catch (err) {
    console.error('Failed to fetch suggestions:', err)
    suggestions.value = []
  } finally {
    loading.value = false
  }
}

function onFocus() {
  isFocused.value = true
}

function onBlur() {
  isFocused.value = false
  selectedIndex.value = -1
}

function onKeydown(e) {
  if (!showSuggestions.value || suggestions.value.length === 0) {
    if (e.key === 'Enter' && query.value.trim()) {
      executeSearch(query.value.trim())
    }
    return
  }

  switch (e.key) {
    case 'ArrowDown':
      e.preventDefault()
      selectedIndex.value = (selectedIndex.value + 1) % suggestions.value.length
      break
    case 'ArrowUp':
      e.preventDefault()
      selectedIndex.value = selectedIndex.value <= 0
        ? suggestions.value.length - 1
        : selectedIndex.value - 1
      break
    case 'Enter':
      e.preventDefault()
      if (selectedIndex.value >= 0) {
        selectSuggestion(suggestions.value[selectedIndex.value])
      } else if (query.value.trim()) {
        executeSearch(query.value.trim())
      }
      break
    case 'Escape':
      inputRef.value?.blur()
      break
  }
}

function selectSuggestion(suggestion) {
  query.value = suggestion.query
  executeSearch(suggestion.query)
}

async function executeSearch(searchQuery) {
  searchedQuery.value = searchQuery
  suggestions.value = []

  try {
    await axios.post(`${API_BASE}/queries`, { query: searchQuery })
  } catch (err) {
    console.error('Failed to record query:', err)
  }
}

function clearQuery() {
  query.value = ''
  suggestions.value = []
  searchedQuery.value = ''
  inputRef.value?.focus()
}

function highlightMatch(text) {
  const prefix = query.value.trim().toLowerCase()
  if (!prefix) return text
  const idx = text.toLowerCase().indexOf(prefix)
  if (idx === -1) return text
  const before = text.slice(0, idx)
  const match = text.slice(idx, idx + prefix.length)
  const after = text.slice(idx + prefix.length)
  return `${before}<strong>${match}</strong>${after}`
}

function getFrequencyWidth(freq) {
  if (suggestions.value.length === 0) return 0
  const maxFreq = Math.max(...suggestions.value.map(s => s.frequency))
  return maxFreq > 0 ? (freq / maxFreq) * 100 : 0
}

function formatFrequency(freq) {
  if (freq >= 1000) return (freq / 1000).toFixed(1) + 'k'
  return freq.toString()
}
</script>

<style scoped>
.search-container {
  position: relative;
  width: 100%;
}

.search-box {
  display: flex;
  align-items: center;
  background: white;
  border-radius: 16px;
  padding: 0 1.2rem;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
  transition: box-shadow 0.3s, transform 0.2s;
}

.search-box.focused {
  box-shadow: 0 6px 30px rgba(0, 0, 0, 0.25);
  transform: translateY(-1px);
}

.search-icon {
  width: 22px;
  height: 22px;
  color: #999;
  flex-shrink: 0;
}

.search-input {
  flex: 1;
  border: none;
  outline: none;
  font-size: 1.1rem;
  padding: 1rem 0.75rem;
  background: transparent;
  color: #333;
}

.search-input::placeholder {
  color: #aaa;
}

.clear-btn {
  background: none;
  border: none;
  font-size: 1.5rem;
  color: #999;
  cursor: pointer;
  padding: 0 0.25rem;
  line-height: 1;
  transition: color 0.2s;
}

.clear-btn:hover {
  color: #e53e3e;
}

/* Suggestions Dropdown */
.suggestions {
  position: absolute;
  top: calc(100% + 8px);
  left: 0;
  right: 0;
  background: white;
  border-radius: 12px;
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.15);
  overflow: hidden;
  z-index: 100;
}

.suggestion-item {
  display: flex;
  align-items: center;
  padding: 0.75rem 1.2rem;
  cursor: pointer;
  transition: background 0.15s;
}

.suggestion-item:hover,
.suggestion-item.active {
  background: #f0f4ff;
}

.suggestion-item.loading,
.suggestion-item.empty {
  color: #999;
  font-size: 0.9rem;
  cursor: default;
}

.suggestion-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.suggestion-text {
  font-size: 0.95rem;
  color: #333;
}

.suggestion-text :deep(strong) {
  color: #667eea;
  font-weight: 600;
}

.frequency-bar {
  height: 3px;
  background: #eee;
  border-radius: 2px;
  overflow: hidden;
  max-width: 200px;
}

.frequency-fill {
  height: 100%;
  background: linear-gradient(90deg, #667eea, #764ba2);
  border-radius: 2px;
  transition: width 0.3s ease;
}

.frequency-count {
  font-size: 0.8rem;
  color: #999;
  margin-left: 1rem;
  min-width: 36px;
  text-align: right;
}

/* Search Result */
.search-result {
  margin-top: 1.5rem;
  background: rgba(255, 255, 255, 0.95);
  border-radius: 12px;
  padding: 1.25rem 1.5rem;
  text-align: center;
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
}

.search-result p {
  font-size: 1rem;
  color: #555;
}

.search-result strong {
  color: #667eea;
}

.result-note {
  font-size: 0.8rem !important;
  color: #999 !important;
  margin-top: 0.5rem;
}
</style>
