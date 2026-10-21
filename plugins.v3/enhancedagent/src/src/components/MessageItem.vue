<script setup>
// 单条展示消息：按 segments 顺序渲染文本与工具卡片，含附件与选择卡。
import ToolCard from './ToolCard.vue'

defineProps({
  message: { type: Object, required: true },
})

const emit = defineEmits(['choice'])
</script>

<template>
  <div class="mi-root" :class="`mi-${message.role}`">
    <div class="mi-role">{{ message.role === 'user' ? '我' : 'Agent' }}</div>
    <div class="mi-body">
      <div v-if="message.thinking" class="mi-thinking">
        思考中<span v-if="message.thinking_elapsed_ms">（{{ Math.round(message.thinking_elapsed_ms / 1000) }}s）</span>…
      </div>

      <template v-if="(message.segments || []).length">
        <template v-for="(segment, index) in message.segments" :key="index">
          <div v-if="segment.type === 'text'" class="mi-text">{{ segment.content }}</div>
          <ToolCard
            v-else-if="segment.type === 'tool' && message.tools[segment.toolIndex]"
            :tool="message.tools[segment.toolIndex]"
          />
        </template>
      </template>
      <template v-else>
        <div v-if="message.content" class="mi-text">{{ message.content }}</div>
        <ToolCard v-for="tool in message.tools || []" :key="tool.id" :tool="tool" />
      </template>

      <div v-if="(message.attachments || []).length" class="mi-attachments">
        <a
          v-for="attachment in message.attachments"
          :key="attachment.ref || attachment.name"
          class="mi-attachment"
          :href="attachment.ref"
          target="_blank"
          rel="noreferrer"
        >📎 {{ attachment.name || '附件' }}</a>
      </div>

      <div
        v-for="choice in message.choices || []"
        :key="choice.id"
        class="mi-choice"
      >
        <div class="mi-choice-title">{{ choice.title || choice.prompt }}</div>
        <div class="mi-choice-buttons">
          <button
            v-for="button in choice.buttons || []"
            :key="button.value"
            class="mi-choice-btn"
            :disabled="choice.status !== 'pending'"
            @click="emit('choice', message, choice, button)"
          >{{ button.label }}</button>
        </div>
        <div v-if="choice.selected_label" class="mi-choice-selected">已选择：{{ choice.selected_label }}</div>
      </div>

      <div v-if="message.status === 'error'" class="mi-error">（该轮回复失败，可重新发送）</div>
    </div>
  </div>
</template>

<style scoped>
.mi-root {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
}
.mi-role {
  width: 44px;
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 600;
  opacity: 0.7;
  padding-top: 3px;
  text-align: right;
}
.mi-user .mi-role {
  color: #2b6cb0;
}
.mi-body {
  flex: 1;
  min-width: 0;
}
.mi-text {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.7;
}
.mi-thinking {
  color: rgba(128, 128, 128, 0.95);
  font-size: 12.5px;
  margin-bottom: 4px;
}
.mi-attachments {
  margin-top: 6px;
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.mi-attachment {
  font-size: 12.5px;
  color: #2b6cb0;
  text-decoration: none;
}
.mi-choice {
  margin-top: 8px;
  padding: 10px 12px;
  border: 1px solid rgba(43, 108, 176, 0.35);
  border-radius: 8px;
}
.mi-choice-title {
  font-size: 13px;
  margin-bottom: 6px;
}
.mi-choice-buttons {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.mi-choice-btn {
  padding: 5px 14px;
  border: 1px solid #2b6cb0;
  border-radius: 6px;
  background: transparent;
  color: #2b6cb0;
  cursor: pointer;
}
.mi-choice-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.mi-choice-selected {
  margin-top: 6px;
  font-size: 12px;
  color: #2f9e44;
}
.mi-error {
  margin-top: 4px;
  color: #c0392b;
  font-size: 12.5px;
}
</style>
