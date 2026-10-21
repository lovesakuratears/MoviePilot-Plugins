<script setup>
// 工具调用卡片：名称、提示与运行状态。
import { computed } from 'vue'

const props = defineProps({
  tool: { type: Object, required: true },
})

const statusText = computed(
  () => ({ running: '执行中', done: '完成', error: '失败' })[props.tool.status] || props.tool.status,
)
</script>

<template>
  <div class="tc-root" :class="`tc-${tool.status || 'done'}`">
    <span class="tc-status">{{ tool.status === 'running' ? '⟳' : tool.status === 'error' ? '✕' : '✓' }}</span>
    <span class="tc-name">{{ tool.tool_name || '工具调用' }}</span>
    <span v-if="tool.message" class="tc-msg">{{ tool.message }}</span>
    <span class="tc-state">{{ statusText }}</span>
  </div>
</template>

<style scoped>
.tc-root {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 10px;
  margin: 3px 0;
  border-radius: 6px;
  font-size: 12.5px;
  background: rgba(128, 128, 128, 0.1);
  border-left: 3px solid rgba(128, 128, 128, 0.5);
}
.tc-running {
  border-left-color: #2b6cb0;
  background: rgba(43, 108, 176, 0.08);
}
.tc-error {
  border-left-color: #c0392b;
  background: rgba(192, 57, 43, 0.08);
}
.tc-done {
  border-left-color: #2f9e44;
}
.tc-msg {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  opacity: 0.85;
}
.tc-state {
  opacity: 0.7;
  white-space: nowrap;
}
</style>
