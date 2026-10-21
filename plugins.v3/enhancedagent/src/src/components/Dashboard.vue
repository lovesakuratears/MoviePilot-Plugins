<script setup>
// 仪表板占位组件：一期未提供仪表板内容。
defineProps({
  config: { type: Object, default: () => ({}) },
  allowRefresh: { type: Boolean, default: false },
})
</script>

<template>
  <div class="db-root">AI 助手暂无仪表板内容。</div>
</template>

<style scoped>
.db-root {
  padding: 12px;
  opacity: 0.75;
  font-size: 13px;
}
</style>
