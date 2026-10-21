<script setup>
// 插件配置表单（vue 模式由宿主挂载）。
// 一期仅保留启用开关；上下文窗口/压缩参数等调优项按 PRD O7 二期接入。
import { reactive } from 'vue'

const props = defineProps({
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: Object, default: null },
})

const emit = defineEmits(['save', 'close'])

const form = reactive({
  enabled: props.initialConfig.enabled !== false,
})

function onSave() {
  emit('save', { enabled: form.enabled })
}
</script>

<template>
  <div class="cf-root">
    <label class="cf-row">
      <input v-model="form.enabled" type="checkbox" />
      <span>启用插件（启用后侧边栏显示「AI 助手」入口）</span>
    </label>
    <p class="cf-hint">
      二期将在此提供上下文窗口、压缩策略等 Agent 调优项（PRD O1/O2/O7）。
    </p>
    <div class="cf-actions">
      <button class="cf-btn" @click="onSave">保存</button>
      <button class="cf-btn cf-btn-plain" @click="emit('close')">取消</button>
    </div>
  </div>
</template>

<style scoped>
.cf-root {
  padding: 12px 4px;
  font-size: 14px;
}
.cf-row {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}
.cf-hint {
  margin: 12px 0 0;
  font-size: 12.5px;
  opacity: 0.75;
}
.cf-actions {
  margin-top: 16px;
  display: flex;
  gap: 8px;
}
.cf-btn {
  padding: 6px 18px;
  border: none;
  border-radius: 6px;
  background: #2b6cb0;
  color: #fff;
  cursor: pointer;
}
.cf-btn-plain {
  background: transparent;
  border: 1px solid rgba(128, 128, 128, 0.5);
  color: inherit;
}
</style>
