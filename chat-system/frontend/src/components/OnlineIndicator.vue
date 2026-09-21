<template>
  <span class="indicator" :class="status"></span>
</template>

<script setup>
defineProps({
  status: { type: String, default: 'offline' }
})
</script>

<style scoped>
.indicator {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  margin-right: 6px;
}
.indicator.online { background-color: #2ecc71; }
.indicator.offline { background-color: #bdc3c7; }
</style>
