import { importShared } from './__federation_fn_import.js';
import { _ as _export_sfc } from './_plugin-vue_export-helper.js';

// 插件桥接 API 封装：统一走 plugin/{pluginId}/* 路径（宿主注入的 api 对象自动携带鉴权）。

function unwrap(res) {
  if (res && typeof res === 'object' && 'success' in res) {
    if (!res.success) {
      throw new Error(res.message || '请求失败')
    }
    return res.data
  }
  return res
}

function useAgentApi(api, pluginId) {
  const base = `plugin/${pluginId}`;

  const call = (method, path, body) => {
    const fn = api && api[method];
    if (typeof fn !== 'function') {
      return Promise.reject(new Error(`注入的 api 对象不支持 ${method} 方法`))
    }
    return Promise.resolve(fn.call(api, path, body)).then(unwrap)
  };

  return {
    /** 签发一次性 SSE 票据 */
    issueTicket: () => call('post', `${base}/sse_ticket`, {}),
    /** 历史会话列表 */
    listSessions: (page = 1, count = 50) =>
      call('get', `${base}/sessions?page=${page}&count=${count}`),
    /** 会话详情（含展示消息与 is_processing） */
    getSession: (sessionId) => call('get', `${base}/sessions/${sessionId}`),
    /** 保存展示消息快照（可携带标题） */
    saveDisplay: (sessionId, body) => call('put', `${base}/sessions/${sessionId}/display`, body),
    /** 删除会话 */
    deleteSession: (sessionId) => call('delete', `${base}/sessions/${sessionId}`),
    /** 停止会话当前任务 */
    stopSession: (sessionId) => call('post', `${base}/sessions/${sessionId}/stop`, {}),
    /** 批量查询会话运行态 */
    sessionsBusy: (sessionIds) => call('post', `${base}/sessions_busy`, { session_ids: sessionIds }),
  }
}

// fetch + ReadableStream 的 SSE 消费器（EventSource 不支持 POST 与自定义头）。
// 帧格式与内置 Agent 一致：`data: {json}` 为主，`event: <name>` 为具名事件，
// `: heartbeat` 注释行为心跳。

function parseFrame(raw) {
  let eventName = '';
  const dataLines = [];
  for (const line of raw.split('\n')) {
    if (line.startsWith(':')) continue
    if (line.startsWith('event:')) eventName = line.slice(6).trim();
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
  }
  if (!dataLines.length) return null
  try {
    const data = JSON.parse(dataLines.join('\n'));
    return eventName ? { ...data, __event: eventName } : data
  } catch {
    return null
  }
}

/**
 * 消费流式对话。
 * @param {object} options 入参
 * @param {string} options.url 流式端点（含一次性票据）
 * @param {object} options.payload 对话请求体
 * @param {(event: object) => void} options.onEvent 事件回调
 * @param {AbortSignal} [options.signal] 取消信号
 */
async function runAgentStream({ url, payload, onEvent, signal }) {
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  });
  if (!resp.ok || !resp.body) {
    throw new Error(`流式请求失败（HTTP ${resp.status}）`)
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break
    buffer += decoder.decode(value, { stream: true });
    let index;
    while ((index = buffer.indexOf('\n\n')) >= 0) {
      const frame = buffer.slice(0, index);
      buffer = buffer.slice(index + 2);
      const event = parseFrame(frame);
      if (event) onEvent(event);
    }
  }
}

const {createElementVNode:_createElementVNode$4,openBlock:_openBlock$4,createElementBlock:_createElementBlock$4,createCommentVNode:_createCommentVNode$4,renderList:_renderList$2,Fragment:_Fragment$2,toDisplayString:_toDisplayString$4,createTextVNode:_createTextVNode$1,withModifiers:_withModifiers$1,normalizeClass:_normalizeClass$2} = await importShared('vue');


const _hoisted_1$4 = { class: "sl-root" };
const _hoisted_2$4 = {
  key: 0,
  class: "sl-empty"
};
const _hoisted_3$4 = ["onClick"];
const _hoisted_4$4 = { class: "sl-item-main" };
const _hoisted_5$3 = { class: "sl-item-title" };
const _hoisted_6$3 = {
  key: 0,
  class: "sl-badge",
  title: "运行中"
};
const _hoisted_7$1 = { class: "sl-item-preview" };
const _hoisted_8$1 = { class: "sl-item-time" };
const _hoisted_9$1 = ["onClick"];
const _hoisted_10$1 = {
  key: 0,
  class: "sl-menu"
};
const _hoisted_11$1 = ["onClick"];
const _hoisted_12$1 = ["onClick"];

const {ref: ref$2} = await importShared('vue');



const _sfc_main$4 = {
  __name: 'SessionList',
  props: {
  sessions: { type: Array, default: () => [] },
  activeId: { type: String, default: '' },
  busyMap: { type: Object, default: () => ({}) },
},
  emits: ['new', 'select', 'rename', 'remove'],
  setup(__props, { emit: __emit }) {

const emit = __emit;

const menuFor = ref$2('');

function formatTime(value) {
  if (!value) return ''
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value)
  const now = Date.now();
  const diff = now - date.getTime();
  if (diff < 60 * 1000) return '刚刚'
  if (diff < 60 * 60 * 1000) return `${Math.floor(diff / 60000)} 分钟前`
  if (diff < 24 * 60 * 60 * 1000) return `${Math.floor(diff / 3600000)} 小时前`
  return date.toLocaleDateString()
}

function onRename(session) {
  menuFor.value = '';
  const title = window.prompt('会话标题', session.title || '');
  if (title && title.trim()) emit('rename', session, title.trim());
}

function onRemove(session) {
  menuFor.value = '';
  if (window.confirm(`删除会话「${session.title || '未命名'}」？该操作不可恢复。`)) {
    emit('remove', session);
  }
}

return (_ctx, _cache) => {
  return (_openBlock$4(), _createElementBlock$4("div", _hoisted_1$4, [
    _createElementVNode$4("button", {
      class: "sl-new",
      onClick: _cache[0] || (_cache[0] = $event => (emit('new')))
    }, "＋ 新会话"),
    (!__props.sessions.length)
      ? (_openBlock$4(), _createElementBlock$4("div", _hoisted_2$4, "暂无历史会话"))
      : _createCommentVNode$4("", true),
    (_openBlock$4(true), _createElementBlock$4(_Fragment$2, null, _renderList$2(__props.sessions, (session) => {
      return (_openBlock$4(), _createElementBlock$4("div", {
        key: session.session_id,
        class: _normalizeClass$2(["sl-item", { 'sl-item-on': session.session_id === __props.activeId }]),
        onClick: $event => (emit('select', session))
      }, [
        _createElementVNode$4("div", _hoisted_4$4, [
          _createElementVNode$4("div", _hoisted_5$3, [
            (__props.busyMap[session.session_id])
              ? (_openBlock$4(), _createElementBlock$4("span", _hoisted_6$3, "●"))
              : _createCommentVNode$4("", true),
            _createTextVNode$1(" " + _toDisplayString$4(session.title || '未命名会话'), 1)
          ]),
          _createElementVNode$4("div", _hoisted_7$1, _toDisplayString$4(session.preview || ''), 1),
          _createElementVNode$4("div", _hoisted_8$1, _toDisplayString$4(formatTime(session.updated_at)), 1)
        ]),
        _createElementVNode$4("div", {
          class: "sl-item-menu",
          onClick: _withModifiers$1($event => (menuFor.value = menuFor.value === session.session_id ? '' : session.session_id), ["stop"])
        }, [
          _cache[1] || (_cache[1] = _createTextVNode$1(" ⋯ ", -1)),
          (menuFor.value === session.session_id)
            ? (_openBlock$4(), _createElementBlock$4("div", _hoisted_10$1, [
                _createElementVNode$4("div", {
                  class: "sl-menu-item",
                  onClick: $event => (onRename(session))
                }, "重命名", 8, _hoisted_11$1),
                _createElementVNode$4("div", {
                  class: "sl-menu-item sl-menu-danger",
                  onClick: $event => (onRemove(session))
                }, "删除", 8, _hoisted_12$1)
              ]))
            : _createCommentVNode$4("", true)
        ], 8, _hoisted_9$1)
      ], 10, _hoisted_3$4))
    }), 128))
  ]))
}
}

};
const SessionList = /*#__PURE__*/_export_sfc(_sfc_main$4, [['__scopeId',"data-v-0eb50901"]]);

const {toDisplayString:_toDisplayString$3,createElementVNode:_createElementVNode$3,openBlock:_openBlock$3,createElementBlock:_createElementBlock$3,createCommentVNode:_createCommentVNode$3,normalizeClass:_normalizeClass$1} = await importShared('vue');


const _hoisted_1$3 = { class: "tc-status" };
const _hoisted_2$3 = { class: "tc-name" };
const _hoisted_3$3 = {
  key: 0,
  class: "tc-msg"
};
const _hoisted_4$3 = { class: "tc-state" };

const {computed: computed$1} = await importShared('vue');



const _sfc_main$3 = {
  __name: 'ToolCard',
  props: {
  tool: { type: Object, required: true },
},
  setup(__props) {

// 工具调用卡片：名称、提示与运行状态。
const props = __props;

const statusText = computed$1(
  () => ({ running: '执行中', done: '完成', error: '失败' })[props.tool.status] || props.tool.status,
);

return (_ctx, _cache) => {
  return (_openBlock$3(), _createElementBlock$3("div", {
    class: _normalizeClass$1(["tc-root", `tc-${__props.tool.status || 'done'}`])
  }, [
    _createElementVNode$3("span", _hoisted_1$3, _toDisplayString$3(__props.tool.status === 'running' ? '⟳' : __props.tool.status === 'error' ? '✕' : '✓'), 1),
    _createElementVNode$3("span", _hoisted_2$3, _toDisplayString$3(__props.tool.tool_name || '工具调用'), 1),
    (__props.tool.message)
      ? (_openBlock$3(), _createElementBlock$3("span", _hoisted_3$3, _toDisplayString$3(__props.tool.message), 1))
      : _createCommentVNode$3("", true),
    _createElementVNode$3("span", _hoisted_4$3, _toDisplayString$3(statusText.value), 1)
  ], 2))
}
}

};
const ToolCard = /*#__PURE__*/_export_sfc(_sfc_main$3, [['__scopeId',"data-v-cd1eb36f"]]);

const {toDisplayString:_toDisplayString$2,createElementVNode:_createElementVNode$2,openBlock:_openBlock$2,createElementBlock:_createElementBlock$2,createCommentVNode:_createCommentVNode$2,createTextVNode:_createTextVNode,renderList:_renderList$1,Fragment:_Fragment$1,createBlock:_createBlock$1,normalizeClass:_normalizeClass} = await importShared('vue');


const _hoisted_1$2 = { class: "mi-role" };
const _hoisted_2$2 = { class: "mi-body" };
const _hoisted_3$2 = {
  key: 0,
  class: "mi-thinking"
};
const _hoisted_4$2 = { key: 0 };
const _hoisted_5$2 = {
  key: 0,
  class: "mi-text"
};
const _hoisted_6$2 = {
  key: 0,
  class: "mi-text"
};
const _hoisted_7 = {
  key: 3,
  class: "mi-attachments"
};
const _hoisted_8 = ["href"];
const _hoisted_9 = { class: "mi-choice-title" };
const _hoisted_10 = { class: "mi-choice-buttons" };
const _hoisted_11 = ["disabled", "onClick"];
const _hoisted_12 = {
  key: 0,
  class: "mi-choice-selected"
};
const _hoisted_13 = {
  key: 4,
  class: "mi-error"
};


const _sfc_main$2 = {
  __name: 'MessageItem',
  props: {
  message: { type: Object, required: true },
},
  emits: ['choice'],
  setup(__props, { emit: __emit }) {

// 单条展示消息：按 segments 顺序渲染文本与工具卡片，含附件与选择卡。


const emit = __emit;

return (_ctx, _cache) => {
  return (_openBlock$2(), _createElementBlock$2("div", {
    class: _normalizeClass(["mi-root", `mi-${__props.message.role}`])
  }, [
    _createElementVNode$2("div", _hoisted_1$2, _toDisplayString$2(__props.message.role === 'user' ? '我' : 'Agent'), 1),
    _createElementVNode$2("div", _hoisted_2$2, [
      (__props.message.thinking)
        ? (_openBlock$2(), _createElementBlock$2("div", _hoisted_3$2, [
            _cache[0] || (_cache[0] = _createTextVNode(" 思考中", -1)),
            (__props.message.thinking_elapsed_ms)
              ? (_openBlock$2(), _createElementBlock$2("span", _hoisted_4$2, "（" + _toDisplayString$2(Math.round(__props.message.thinking_elapsed_ms / 1000)) + "s）", 1))
              : _createCommentVNode$2("", true),
            _cache[1] || (_cache[1] = _createTextVNode("… ", -1))
          ]))
        : _createCommentVNode$2("", true),
      ((__props.message.segments || []).length)
        ? (_openBlock$2(true), _createElementBlock$2(_Fragment$1, { key: 1 }, _renderList$1(__props.message.segments, (segment, index) => {
            return (_openBlock$2(), _createElementBlock$2(_Fragment$1, { key: index }, [
              (segment.type === 'text')
                ? (_openBlock$2(), _createElementBlock$2("div", _hoisted_5$2, _toDisplayString$2(segment.content), 1))
                : (segment.type === 'tool' && __props.message.tools[segment.toolIndex])
                  ? (_openBlock$2(), _createBlock$1(ToolCard, {
                      key: 1,
                      tool: __props.message.tools[segment.toolIndex]
                    }, null, 8, ["tool"]))
                  : _createCommentVNode$2("", true)
            ], 64))
          }), 128))
        : (_openBlock$2(), _createElementBlock$2(_Fragment$1, { key: 2 }, [
            (__props.message.content)
              ? (_openBlock$2(), _createElementBlock$2("div", _hoisted_6$2, _toDisplayString$2(__props.message.content), 1))
              : _createCommentVNode$2("", true),
            (_openBlock$2(true), _createElementBlock$2(_Fragment$1, null, _renderList$1(__props.message.tools || [], (tool) => {
              return (_openBlock$2(), _createBlock$1(ToolCard, {
                key: tool.id,
                tool: tool
              }, null, 8, ["tool"]))
            }), 128))
          ], 64)),
      ((__props.message.attachments || []).length)
        ? (_openBlock$2(), _createElementBlock$2("div", _hoisted_7, [
            (_openBlock$2(true), _createElementBlock$2(_Fragment$1, null, _renderList$1(__props.message.attachments, (attachment) => {
              return (_openBlock$2(), _createElementBlock$2("a", {
                key: attachment.ref || attachment.name,
                class: "mi-attachment",
                href: attachment.ref,
                target: "_blank",
                rel: "noreferrer"
              }, "📎 " + _toDisplayString$2(attachment.name || '附件'), 9, _hoisted_8))
            }), 128))
          ]))
        : _createCommentVNode$2("", true),
      (_openBlock$2(true), _createElementBlock$2(_Fragment$1, null, _renderList$1(__props.message.choices || [], (choice) => {
        return (_openBlock$2(), _createElementBlock$2("div", {
          key: choice.id,
          class: "mi-choice"
        }, [
          _createElementVNode$2("div", _hoisted_9, _toDisplayString$2(choice.title || choice.prompt), 1),
          _createElementVNode$2("div", _hoisted_10, [
            (_openBlock$2(true), _createElementBlock$2(_Fragment$1, null, _renderList$1(choice.buttons || [], (button) => {
              return (_openBlock$2(), _createElementBlock$2("button", {
                key: button.value,
                class: "mi-choice-btn",
                disabled: choice.status !== 'pending',
                onClick: $event => (emit('choice', __props.message, choice, button))
              }, _toDisplayString$2(button.label), 9, _hoisted_11))
            }), 128))
          ]),
          (choice.selected_label)
            ? (_openBlock$2(), _createElementBlock$2("div", _hoisted_12, "已选择：" + _toDisplayString$2(choice.selected_label), 1))
            : _createCommentVNode$2("", true)
        ]))
      }), 128)),
      (__props.message.status === 'error')
        ? (_openBlock$2(), _createElementBlock$2("div", _hoisted_13, "（该轮回复失败，可重新发送）"))
        : _createCommentVNode$2("", true)
    ])
  ], 2))
}
}

};
const MessageItem = /*#__PURE__*/_export_sfc(_sfc_main$2, [['__scopeId',"data-v-80bda24f"]]);

const {openBlock:_openBlock$1,createElementBlock:_createElementBlock$1,createCommentVNode:_createCommentVNode$1,renderList:_renderList,Fragment:_Fragment,createBlock:_createBlock,createElementVNode:_createElementVNode$1,vModelText:_vModelText,withModifiers:_withModifiers,withKeys:_withKeys,withDirectives:_withDirectives,toDisplayString:_toDisplayString$1} = await importShared('vue');


const _hoisted_1$1 = { class: "cp-root" };
const _hoisted_2$1 = {
  key: 0,
  class: "cp-hint"
};
const _hoisted_3$1 = {
  key: 1,
  class: "cp-hint"
};
const _hoisted_4$1 = { class: "cp-input" };
const _hoisted_5$1 = ["onKeydown"];
const _hoisted_6$1 = ["disabled"];

const {nextTick,ref: ref$1,watch} = await importShared('vue');


const _sfc_main$1 = {
  __name: 'ChatPane',
  props: {
  messages: { type: Array, default: () => [] },
  streaming: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
},
  emits: ['send', 'choice'],
  setup(__props, { emit: __emit }) {

// 对话面板：消息流 + 输入框 + 选择卡回调。
const props = __props;

const emit = __emit;

const input = ref$1('');
const scrollBox = ref$1(null);

watch(
  () => [props.messages.length, props.messages[props.messages.length - 1]?.content],
  async () => {
    await nextTick();
    if (scrollBox.value) scrollBox.value.scrollTop = scrollBox.value.scrollHeight;
  },
);

function onSubmit() {
  const text = input.value;
  input.value = '';
  emit('send', text);
}

function onChoice(message, choice, button) {
  emit('choice', message, choice, button);
}

return (_ctx, _cache) => {
  return (_openBlock$1(), _createElementBlock$1("div", _hoisted_1$1, [
    _createElementVNode$1("div", {
      ref_key: "scrollBox",
      ref: scrollBox,
      class: "cp-scroll"
    }, [
      (__props.loading)
        ? (_openBlock$1(), _createElementBlock$1("div", _hoisted_2$1, "加载中…"))
        : (!__props.messages.length)
          ? (_openBlock$1(), _createElementBlock$1("div", _hoisted_3$1, " 向内置 Agent 提问，支持多轮工具调用；左侧可管理多个会话。 "))
          : _createCommentVNode$1("", true),
      (_openBlock$1(true), _createElementBlock$1(_Fragment, null, _renderList(__props.messages, (message) => {
        return (_openBlock$1(), _createBlock(MessageItem, {
          key: message.id,
          message: message,
          onChoice: onChoice
        }, null, 8, ["message"]))
      }), 128))
    ], 512),
    _createElementVNode$1("div", _hoisted_4$1, [
      _withDirectives(_createElementVNode$1("textarea", {
        "onUpdate:modelValue": _cache[0] || (_cache[0] = $event => ((input).value = $event)),
        rows: "2",
        placeholder: "输入消息，Enter 发送 / Shift+Enter 换行",
        onKeydown: _withKeys(_withModifiers(onSubmit, ["exact","prevent"]), ["enter"])
      }, null, 40, _hoisted_5$1), [
        [_vModelText, input.value]
      ]),
      _createElementVNode$1("button", {
        class: "cp-send",
        disabled: __props.streaming || !input.value.trim(),
        onClick: onSubmit
      }, _toDisplayString$1(__props.streaming ? '进行中…' : '发送'), 9, _hoisted_6$1)
    ])
  ]))
}
}

};
const ChatPane = /*#__PURE__*/_export_sfc(_sfc_main$1, [['__scopeId',"data-v-2c2e4915"]]);

const {createVNode:_createVNode,createElementVNode:_createElementVNode,toDisplayString:_toDisplayString,openBlock:_openBlock,createElementBlock:_createElementBlock,createCommentVNode:_createCommentVNode} = await importShared('vue');


const _hoisted_1 = { class: "ea-page" };
const _hoisted_2 = { class: "ea-side" };
const _hoisted_3 = { class: "ea-main" };
const _hoisted_4 = { class: "ea-header" };
const _hoisted_5 = { class: "ea-title" };
const _hoisted_6 = {
  key: 0,
  class: "ea-notice"
};

const {computed,onBeforeUnmount,ref} = await importShared('vue');


const _sfc_main = {
  __name: 'AppPage',
  props: {
  api: { type: Object, default: () => ({}) },
  pluginId: { type: String, default: '' },
  navKey: { type: String, default: 'main' },
  sourcePluginId: { type: String, default: '' },
  nativeSubscribe: { type: Function, default: null },
},
  setup(__props) {

// 「AI助手增强」侧边栏全页入口：会话列表 + 流式对话。
const props = __props;

const api = useAgentApi(props.api, props.pluginId);

const sessions = ref([]);
const busyMap = ref({});
const activeSeed = ref('');
const activeServerId = ref('');
const messages = ref([]);
const streaming = ref(false);
const loading = ref(false);
const notice = ref('');

let abortController = null;

function newSeed() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return `seed-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function newSession() {
  cancelStream();
  activeSeed.value = newSeed();
  activeServerId.value = '';
  messages.value = [];
  notice.value = '';
}

async function loadSessions() {
  try {
    const data = await api.listSessions(1, 50);
    sessions.value = Array.isArray(data) ? data : [];
    refreshBusy();
  } catch (error) {
    notice.value = `会话列表加载失败：${error.message}`;
  }
}

async function refreshBusy() {
  const ids = sessions.value
    .map((item) => item.session_id)
    .filter(Boolean);
  if (!ids.length) {
    busyMap.value = {};
    return
  }
  try {
    const data = await api.sessionsBusy(ids);
    busyMap.value = (data && data.busy) || {};
  } catch {
    busyMap.value = {};
  }
}

async function selectSession(session) {
  cancelStream();
  notice.value = '';
  loading.value = true;
  try {
    const data = await api.getSession(session.session_id);
    activeServerId.value = (data && data.session_id) || session.session_id;
    activeSeed.value = (data && data.client_session_id) || session.client_session_id || session.session_id;
    messages.value = Array.isArray(data && data.messages) ? data.messages : [];
  } catch (error) {
    notice.value = `会话加载失败：${error.message}`;
  } finally {
    loading.value = false;
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
  message.content = (message.content || '') + content;
  const segments = message.segments || (message.segments = []);
  if (segments.length && segments[segments.length - 1].type === 'text') {
    segments[segments.length - 1].content = (segments[segments.length - 1].content || '') + content;
  } else {
    segments.push({ type: 'text', content });
  }
}

function applyToolEvent(message, event) {
  const toolId = event.id || event.tool_id;
  const status = event.status || 'running';
  const tools = message.tools || (message.tools = []);
  const segments = message.segments || (message.segments = []);
  if (toolId) {
    const index = tools.findIndex((tool) => tool.id === toolId);
    if (status === 'running') {
      if (index < 0) {
        const toolIndex = tools.length;
        tools.push({
          id: toolId,
          tool_name: event.tool_name || '',
          message: String(event.message || '').trim(),
          status: 'running',
        });
        segments.push({ type: 'tool', toolIndex });
      }
      return
    }
    if (index >= 0) tools[index].status = status;
    return
  }
  tools.forEach((tool) => {
    if (tool.status === 'running') tool.status = 'done';
  });
  const toolIndex = tools.length;
  tools.push({
    id: `tool-${Date.now()}`,
    message: String(event.message || '').trim(),
    status: 'running',
  });
  segments.push({ type: 'tool', toolIndex });
}

// 与内置 Agent 服务端 apply_web_agent_display_event 保持同一套归约语义。
function applyDisplayEvent(message, event) {
  switch (event.type) {
    case 'delta':
      appendText(message, event.content || '');
      break
    case 'tool':
      applyToolEvent(message, event);
      break
    case 'attachment':
      if (event.attachment) message.attachments.push(event.attachment);
      break
    case 'choice':
      if (event.choice) message.choices.push({ ...event.choice, status: 'pending' });
      break
    case 'message_update': {
      const target = event.target_message || {};
      if (target.id) message.id = target.id;
      message.content = target.content || '';
      message.attachments = target.attachments || [];
      message.choices = target.choices || [];
      message.tools = target.tools || [];
      message.segments = Array.isArray(target.segments)
        ? target.segments
        : [
            ...message.tools.map((_, index) => ({ type: 'tool', toolIndex: index })),
            ...(message.content ? [{ type: 'text', content: message.content }] : []),
          ];
      message.status = target.status || 'done';
      break
    }
    case 'thinking':
      message.thinking = String(event.status || '') === 'running';
      if (message.thinking) {
        message.thinking_started_at = event.started_at;
      } else {
        message.thinking_elapsed_ms = event.elapsed_ms || message.thinking_elapsed_ms || 0;
      }
      break
    case 'error':
      message.status = 'error';
      if (!message.content) appendText(message, event.message || '智能助手响应失败');
      message.tools.forEach((tool) => {
        if (tool.status === 'running') tool.status = 'done';
      });
      break
    case 'done':
      message.thinking = false;
      if (message.status === 'streaming') message.status = 'done';
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
    });
    if (data && data.session_id) activeServerId.value = data.session_id;
  } catch {
    // 展示快照保存失败不阻断对话；下次完成时重试
  }
}

async function send(text) {
  const content = String(text || '').trim();
  if (!content || streaming.value) return
  notice.value = '';
  if (!activeSeed.value) newSession();

  const userMessage = buildUserMessage(content);
  const assistantMessage = buildAssistantMessage();
  messages.value.push(userMessage, assistantMessage);

  const isFirstTurn = messages.value.filter((item) => item.role === 'user').length === 1;
  await startStream({
    text: content,
    session_id: activeSeed.value,
    title: isFirstTurn ? content.slice(0, 30) : undefined,
  });
}

async function startStream(payload) {
  streaming.value = true;
  abortController = new AbortController();
  const assistantMessage = messages.value[messages.value.length - 1];
  try {
    const ticketData = await api.issueTicket();
    const ticket = ticketData && ticketData.ticket;
    if (!ticket) throw new Error('票据签发失败')
    await runAgentStream({
      url: `/api/v1/plugin/${props.pluginId}/stream?ticket=${encodeURIComponent(ticket)}`,
      payload,
      signal: abortController.signal,
      onEvent: (event) => {
        if (event.type === 'start' && event.session_id) {
          activeServerId.value = event.session_id;
          return
        }
        applyDisplayEvent(assistantMessage, event);
      },
    });
    if (assistantMessage.status === 'streaming') assistantMessage.status = 'done';
  } catch (error) {
    if (error.name !== 'AbortError') {
      assistantMessage.status = 'error';
      notice.value = `对话中断：${error.message}`;
    }
  } finally {
    streaming.value = false;
    abortController = null;
    await persistDisplay(payload.title ? { title: payload.title } : {});
    loadSessions();
  }
}

async function sendChoice(message, choice, button) {
  if (streaming.value) return
  message.choice_selection = {
    choice_id: choice.id,
    value: button.value,
    label: button.label,
  };
  choice.status = 'done';
  choice.selected_label = button.label;
  choice.selected_value = button.value;
  const assistantMessage = buildAssistantMessage();
  messages.value.push(assistantMessage);
  await startStream({
    text: '',
    session_id: activeSeed.value,
    choice_selection: message.choice_selection,
    original_message_id: message.id,
  });
}

function cancelStream() {
  if (abortController) abortController.abort();
}

async function stopCurrent() {
  cancelStream();
  try {
    await api.stopSession(activeServerId.value || activeSeed.value);
  } catch (error) {
    notice.value = `停止失败：${error.message}`;
  }
}

async function renameSession(session, title) {
  try {
    const detail = await api.getSession(session.session_id);
    await api.saveDisplay(session.session_id, {
      messages: (detail && detail.messages) || [],
      title,
    });
    loadSessions();
  } catch (error) {
    notice.value = `重命名失败：${error.message}`;
  }
}

async function removeSession(session) {
  try {
    await api.deleteSession(session.session_id);
    if (activeServerId.value === session.session_id) newSession();
    loadSessions();
  } catch (error) {
    notice.value = `删除失败：${error.message}`;
  }
}

const activeTitle = computed(() => {
  const found = sessions.value.find((item) => item.session_id === activeServerId.value);
  return (found && found.title) || '新会话'
});

loadSessions();
onBeforeUnmount(cancelStream);

return (_ctx, _cache) => {
  return (_openBlock(), _createElementBlock("div", _hoisted_1, [
    _createElementVNode("aside", _hoisted_2, [
      _createVNode(SessionList, {
        sessions: sessions.value,
        "active-id": activeServerId.value,
        "busy-map": busyMap.value,
        onNew: newSession,
        onSelect: selectSession,
        onRename: renameSession,
        onRemove: removeSession
      }, null, 8, ["sessions", "active-id", "busy-map"])
    ]),
    _createElementVNode("section", _hoisted_3, [
      _createElementVNode("header", _hoisted_4, [
        _createElementVNode("div", _hoisted_5, _toDisplayString(activeTitle.value), 1),
        (streaming.value)
          ? (_openBlock(), _createElementBlock("button", {
              key: 0,
              class: "ea-btn ea-btn-danger",
              onClick: stopCurrent
            }, "停止"))
          : _createCommentVNode("", true)
      ]),
      (notice.value)
        ? (_openBlock(), _createElementBlock("div", _hoisted_6, _toDisplayString(notice.value), 1))
        : _createCommentVNode("", true),
      _createVNode(ChatPane, {
        messages: messages.value,
        streaming: streaming.value,
        loading: loading.value,
        onSend: send,
        onChoice: sendChoice
      }, null, 8, ["messages", "streaming", "loading"])
    ])
  ]))
}
}

};
const AppPage = /*#__PURE__*/_export_sfc(_sfc_main, [['__scopeId',"data-v-cdfb3fd3"]]);

export { AppPage as default };
