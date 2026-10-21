<script setup>
// 「AI助手增强」侧边栏全页入口：会话列表 + 流式对话。
import { computed, onBeforeUnmount, ref } from 'vue'
import { useAgentApi } from '../composables/useAgentApi.js'
import { runAgentStream } from '../composables/useAgentStream.js'
import SessionList from './SessionList.vue'
import ChatPane from './ChatPane.vue'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: '' },
  navKey: { type: String, default: 'main' },
  sourcePluginId: { type: String, default: '' },
  nativeSubscribe: { type: Function, default: null },
})

const api = useAgentApi(props.api, props.pluginId)

const sessions = ref([])
const busyMap = ref({})
const activeSeed = ref('')
const activeServerId = ref('')
const messages = ref([])
const streaming = ref(false)
const loading = ref(false)
const notice = ref('')

let abortController = null

function newSeed() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return `seed-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function newSession() {
  cancelStream()
  activeSeed.value = newSeed()
  activeServerId.value = ''
  messages.value = []
  notice.value = ''
}

async function loadSessions() {
  try {
    const data = await api.listSessions(1, 50)
    sessions.value = Array.isArray(data) ? data : []
    refreshBusy()
  } catch (error) {
    notice.value = `会话列表加载失败：${error.message}`
  }
}

async function refreshBusy() {
  const ids = sessions.value
    .map((item) => item.session_id)
    .filter(Boolean)
  if (!ids.length) {
    busyMap.value = {}
    return
  }
  try {
    const data = await api.sessionsBusy(ids)
    busyMap.value = (data && data.busy) || {}
  } catch {
    busyMap.value = {}
  }
}

async function selectSession(session) {
  cancelStream()
  notice.value = ''
  loading.value = true
  try {
    const data = await api.getSession(session.session_id)
    activeServerId.value = (data && data.session_id) || session.session_id
    activeSeed.value = (data && data.client_session_id) || session.client_session_id || session.session_id
    messages.value = Array.isArray(data && data.messages) ? data.messages : []
  } catch (error) {
    notice.value = `会话加载失败：${error.message}`
  } finally {
    loading.value = false
  }
}

function buildUserMessage(text) {
  return {
    id: `local-${Date.now()}`,
    role: 'user',
    content: text,
    createdAt: Date.now(),
    status: 'done',
    tools: [],
    segments: [{ type: 'text', content: text }],
    attachments: [],
    choices: [],
  }
}

function buildAssistantMessage() {
  return {
    id: `local-${Date.now()}-a`,
    role: 'assistant',
    content: '',
    createdAt: Date.now(),
    status: 'streaming',
    tools: [],
    segments: [],
    attachments: [],
    choices: [],
    thinking: false,
  }
}

function appendText(message, content) {
  if (!content) return
  message.content = (message.content || '') + content
  const segments = message.segments || (message.segments = [])
  if (segments.length && segments[segments.length - 1].type === 'text') {
    segments[segments.length - 1].content = (segments[segments.length - 1].content || '') + content
  } else {
    segments.push({ type: 'text', content })
  }
}

function applyToolEvent(message, event) {
  const toolId = event.id || event.tool_id
  const status = event.status || 'running'
  const tools = message.tools || (message.tools = [])
  const segments = message.segments || (message.segments = [])
  if (toolId) {
    const index = tools.findIndex((tool) => tool.id === toolId)
    if (status === 'running') {
      if (index < 0) {
        const toolIndex = tools.length
        tools.push({
          id: toolId,
          tool_name: event.tool_name || '',
          message: String(event.message || '').trim(),
          status: 'running',
        })
        segments.push({ type: 'tool', toolIndex })
      }
      return
    }
    if (index >= 0) tools[index].status = status
    return
  }
  tools.forEach((tool) => {
    if (tool.status === 'running') tool.status = 'done'
  })
  const toolIndex = tools.length
  tools.push({
    id: `tool-${Date.now()}`,
    message: String(event.message || '').trim(),
    status: 'running',
  })
  segments.push({ type: 'tool', toolIndex })
}

// 与内置 Agent 服务端 apply_web_agent_display_event 保持同一套归约语义。
function applyDisplayEvent(message, event) {
  switch (event.type) {
    case 'delta':
      appendText(message, event.content || '')
      break
    case 'tool':
      applyToolEvent(message, event)
      break
    case 'attachment':
      if (event.attachment) message.attachments.push(event.attachment)
      break
    case 'choice':
      if (event.choice) message.choices.push({ ...event.choice, status: 'pending' })
      break
    case 'message_update': {
      const target = event.target_message || {}
      if (target.id) message.id = target.id
      message.content = target.content || ''
      message.attachments = target.attachments || []
      message.choices = target.choices || []
      message.tools = target.tools || []
      message.segments = Array.isArray(target.segments)
        ? target.segments
        : [
            ...message.tools.map((_, index) => ({ type: 'tool', toolIndex: index })),
            ...(message.content ? [{ type: 'text', content: message.content }] : []),
          ]
      message.status = target.status || 'done'
      break
    }
    case 'thinking':
      message.thinking = String(event.status || '') === 'running'
      if (message.thinking) {
        message.thinking_started_at = event.started_at
      } else {
        message.thinking_elapsed_ms = event.elapsed_ms || message.thinking_elapsed_ms || 0
      }
      break
    case 'error':
      message.status = 'error'
      if (!message.content) appendText(message, event.message || '智能助手响应失败')
      message.tools.forEach((tool) => {
        if (tool.status === 'running') tool.status = 'done'
      })
      break
    case 'done':
      message.thinking = false
      if (message.status === 'streaming') message.status = 'done'
      break
    default:
      break
  }
}

function savePayloadMessages() {
  return messages.value.map((message) => ({
    id: message.id,
    role: message.role,
    content: message.content || '',
    createdAt: message.createdAt,
    status: message.status === 'streaming' ? 'done' : message.status || 'done',
    tools: (message.tools || []).map((tool) => ({
      id: tool.id,
      tool_name: tool.tool_name || '',
      message: tool.message || '',
      status: tool.status || 'done',
    })),
    segments: message.segments || [],
    attachments: message.attachments || [],
    choices: message.choices || [],
    choice_selection: message.choice_selection || undefined,
  }))
}

async function persistDisplay(extra = {}) {
  if (!activeServerId.value && !activeSeed.value) return
  try {
    const data = await api.saveDisplay(activeServerId.value || activeSeed.value, {
      messages: savePayloadMessages(),
      ...extra,
    })
    if (data && data.session_id) activeServerId.value = data.session_id
  } catch {
    // 展示快照保存失败不阻断对话；下次完成时重试
  }
}

async function send(text) {
  const content = String(text || '').trim()
  if (!content || streaming.value) return
  notice.value = ''
  if (!activeSeed.value) newSession()

  const userMessage = buildUserMessage(content)
  const assistantMessage = buildAssistantMessage()
  messages.value.push(userMessage, assistantMessage)

  const isFirstTurn = messages.value.filter((item) => item.role === 'user').length === 1
  await startStream({
    text: content,
    session_id: activeSeed.value,
    title: isFirstTurn ? content.slice(0, 30) : undefined,
  })
}

async function startStream(payload) {
  streaming.value = true
  abortController = new AbortController()
  const assistantMessage = messages.value[messages.value.length - 1]
  try {
    const ticketData = await api.issueTicket()
    const ticket = ticketData && ticketData.ticket
    if (!ticket) throw new Error('票据签发失败')
    await runAgentStream({
      url: `/api/v1/plugin/${props.pluginId}/stream?ticket=${encodeURIComponent(ticket)}`,
      payload,
      signal: abortController.signal,
      onEvent: (event) => {
        if (event.type === 'start' && event.session_id) {
          activeServerId.value = event.session_id
          return
        }
        applyDisplayEvent(assistantMessage, event)
      },
    })
    if (assistantMessage.status === 'streaming') assistantMessage.status = 'done'
  } catch (error) {
    if (error.name !== 'AbortError') {
      assistantMessage.status = 'error'
      notice.value = `对话中断：${error.message}`
    }
  } finally {
    streaming.value = false
    abortController = null
    await persistDisplay(payload.title ? { title: payload.title } : {})
    loadSessions()
  }
}

async function sendChoice(message, choice, button) {
  if (streaming.value) return
  message.choice_selection = {
    choice_id: choice.id,
    value: button.value,
    label: button.label,
  }
  choice.status = 'done'
  choice.selected_label = button.label
  choice.selected_value = button.value
  const assistantMessage = buildAssistantMessage()
  messages.value.push(assistantMessage)
  await startStream({
    text: '',
    session_id: activeSeed.value,
    choice_selection: message.choice_selection,
    original_message_id: message.id,
  })
}

function cancelStream() {
  if (abortController) abortController.abort()
}

async function stopCurrent() {
  cancelStream()
  try {
    await api.stopSession(activeServerId.value || activeSeed.value)
  } catch (error) {
    notice.value = `停止失败：${error.message}`
  }
}

async function renameSession(session, title) {
  try {
    const detail = await api.getSession(session.session_id)
    await api.saveDisplay(session.session_id, {
      messages: (detail && detail.messages) || [],
      title,
    })
    loadSessions()
  } catch (error) {
    notice.value = `重命名失败：${error.message}`
  }
}

async function removeSession(session) {
  try {
    await api.deleteSession(session.session_id)
    if (activeServerId.value === session.session_id) newSession()
    loadSessions()
  } catch (error) {
    notice.value = `删除失败：${error.message}`
  }
}

const activeTitle = computed(() => {
  const found = sessions.value.find((item) => item.session_id === activeServerId.value)
  return (found && found.title) || '新会话'
})

loadSessions()
onBeforeUnmount(cancelStream)
</script>

<template>
  <div class="ea-page">
    <aside class="ea-side">
      <SessionList
        :sessions="sessions"
        :active-id="activeServerId"
        :busy-map="busyMap"
        @new="newSession"
        @select="selectSession"
        @rename="renameSession"
        @remove="removeSession"
      />
    </aside>
    <section class="ea-main">
      <header class="ea-header">
        <div class="ea-title">{{ activeTitle }}</div>
        <button v-if="streaming" class="ea-btn ea-btn-danger" @click="stopCurrent">停止</button>
      </header>
      <div v-if="notice" class="ea-notice">{{ notice }}</div>
      <ChatPane
        :messages="messages"
        :streaming="streaming"
        :loading="loading"
        @send="send"
        @choice="sendChoice"
      />
    </section>
  </div>
</template>

<style scoped>
.ea-page {
  display: flex;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}
.ea-side {
  width: 260px;
  flex-shrink: 0;
  border-right: 1px solid rgba(128, 128, 128, 0.25);
  overflow-y: auto;
}
.ea-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.ea-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-bottom: 1px solid rgba(128, 128, 128, 0.25);
}
.ea-title {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ea-notice {
  padding: 6px 16px;
  background: rgba(220, 53, 69, 0.12);
  color: #c0392b;
  font-size: 13px;
}
.ea-btn {
  border: none;
  border-radius: 6px;
  padding: 6px 14px;
  cursor: pointer;
  font-size: 13px;
  background: #2b6cb0;
  color: #fff;
}
.ea-btn-danger {
  background: #c0392b;
}
</style>
