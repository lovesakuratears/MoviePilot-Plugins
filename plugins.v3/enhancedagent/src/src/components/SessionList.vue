<script setup>
// 会话列表：新建 / 切换 / 重命名 / 删除，运行态徽标。
import { ref } from 'vue'

const props = defineProps({
  sessions: { type: Array, default: () => [] },
  activeId: { type: String, default: '' },
  busyMap: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['new', 'select', 'rename', 'remove'])

const menuFor = ref('')

function formatTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const now = Date.now()
  const diff = now - date.getTime()
  if (diff < 60 * 1000) return '刚刚'
  if (diff < 60 * 60 * 1000) return `${Math.floor(diff / 60000)} 分钟前`
  if (diff < 24 * 60 * 60 * 1000) return `${Math.floor(diff / 3600000)} 小时前`
  return date.toLocaleDateString()
}

function onRename(session) {
  menuFor.value = ''
  const title = window.prompt('会话标题', session.title || '')
  if (title && title.trim()) emit('rename', session, title.trim())
}

function onRemove(session) {
  menuFor.value = ''
  if (window.confirm(`删除会话「${session.title || '未命名'}」？该操作不可恢复。`)) {
    emit('remove', session)
  }
}
</script>

<template>
  <div class="sl-root">
    <button class="sl-new" @click="emit('new')">＋ 新会话</button>
    <div v-if="!sessions.length" class="sl-empty">暂无历史会话</div>
    <div
      v-for="session in sessions"
      :key="session.session_id"
      class="sl-item"
      :class="{ 'sl-item-on': session.session_id === activeId }"
      @click="emit('select', session)"
    >
      <div class="sl-item-main">
        <div class="sl-item-title">
          <span
            v-if="busyMap[session.session_id]"
            class="sl-badge"
            title="运行中"
          >●</span>
          {{ session.title || '未命名会话' }}
        </div>
        <div class="sl-item-preview">{{ session.preview || '' }}</div>
        <div class="sl-item-time">{{ formatTime(session.updated_at) }}</div>
      </div>
      <div class="sl-item-menu" @click.stop="menuFor = menuFor === session.session_id ? '' : session.session_id">
        ⋯
        <div v-if="menuFor === session.session_id" class="sl-menu">
          <div class="sl-menu-item" @click="onRename(session)">重命名</div>
          <div class="sl-menu-item sl-menu-danger" @click="onRemove(session)">删除</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sl-root {
  padding: 10px;
  font-size: 13px;
}
.sl-new {
  width: 100%;
  padding: 8px 0;
  border: 1px dashed rgba(128, 128, 128, 0.5);
  border-radius: 6px;
  background: transparent;
  cursor: pointer;
  margin-bottom: 10px;
}
.sl-empty {
  color: rgba(128, 128, 128, 0.9);
  text-align: center;
  padding: 24px 0;
}
.sl-item {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 4px;
  padding: 8px;
  border-radius: 6px;
  cursor: pointer;
}
.sl-item:hover {
  background: rgba(43, 108, 176, 0.08);
}
.sl-item-on {
  background: rgba(43, 108, 176, 0.16);
}
.sl-item-main {
  flex: 1;
  min-width: 0;
}
.sl-item-title {
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sl-badge {
  color: #2f9e44;
  font-size: 10px;
}
.sl-item-preview {
  color: rgba(128, 128, 128, 0.95);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sl-item-time {
  color: rgba(128, 128, 128, 0.8);
  font-size: 11px;
}
.sl-item-menu {
  position: relative;
  padding: 0 4px;
  color: rgba(128, 128, 128, 0.9);
  user-select: none;
}
.sl-menu {
  position: absolute;
  right: 0;
  top: 18px;
  z-index: 10;
  background: #fff;
  border: 1px solid rgba(128, 128, 128, 0.3);
  border-radius: 6px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  min-width: 96px;
}
.sl-menu-item {
  padding: 6px 12px;
  cursor: pointer;
}
.sl-menu-item:hover {
  background: rgba(43, 108, 176, 0.1);
}
.sl-menu-danger {
  color: #c0392b;
}
</style>
