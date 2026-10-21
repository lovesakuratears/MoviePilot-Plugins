<script setup>
// 对话面板：消息流 + 输入框 + 选择卡回调。
import { nextTick, ref, watch } from 'vue'
import MessageItem from './MessageItem.vue'

const props = defineProps({
  messages: { type: Array, default: () => [] },
  streaming: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
})

const emit = defineEmits(['send', 'choice'])

const input = ref('')
const scrollBox = ref(null)

watch(
  () => [props.messages.length, props.messages[props.messages.length - 1]?.content],
  async () => {
    await nextTick()
    if (scrollBox.value) scrollBox.value.scrollTop = scrollBox.value.scrollHeight
  },
)

function onSubmit() {
  const text = input.value
  input.value = ''
  emit('send', text)
}

function onChoice(message, choice, button) {
  emit('choice', message, choice, button)
}
</script>

<template>
  <div class="cp-root">
    <div ref="scrollBox" class="cp-scroll">
      <div v-if="loading" class="cp-hint">加载中…</div>
      <div v-else-if="!messages.length" class="cp-hint">
        向内置 Agent 提问，支持多轮工具调用；左侧可管理多个会话。
      </div>
      <MessageItem
        v-for="message in messages"
        :key="message.id"
        :message="message"
        @choice="onChoice"
      />
    </div>
    <div class="cp-input">
      <textarea
        v-model="input"
        rows="2"
        placeholder="输入消息，Enter 发送 / Shift+Enter 换行"
        @keydown.enter.exact.prevent="onSubmit"
      />
      <button class="cp-send" :disabled="streaming || !input.trim()" @click="onSubmit">
        {{ streaming ? '进行中…' : '发送' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.cp-root {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.cp-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}
.cp-hint {
  color: rgba(128, 128, 128, 0.9);
  text-align: center;
  padding: 48px 0;
}
.cp-input {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid rgba(128, 128, 128, 0.25);
}
.cp-input textarea {
  flex: 1;
  resize: none;
  border: 1px solid rgba(128, 128, 128, 0.4);
  border-radius: 6px;
  padding: 8px 10px;
  font: inherit;
}
.cp-send {
  align-self: flex-end;
  padding: 8px 20px;
  border: none;
  border-radius: 6px;
  background: #2b6cb0;
  color: #fff;
  cursor: pointer;
}
.cp-send:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
