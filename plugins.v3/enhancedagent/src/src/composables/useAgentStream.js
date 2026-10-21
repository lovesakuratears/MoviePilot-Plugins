// fetch + ReadableStream 的 SSE 消费器（EventSource 不支持 POST 与自定义头）。
// 帧格式与内置 Agent 一致：`data: {json}` 为主，`event: <name>` 为具名事件，
// `: heartbeat` 注释行为心跳。

function parseFrame(raw) {
  let eventName = ''
  const dataLines = []
  for (const line of raw.split('\n')) {
    if (line.startsWith(':')) continue
    if (line.startsWith('event:')) eventName = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
  }
  if (!dataLines.length) return null
  try {
    const data = JSON.parse(dataLines.join('\n'))
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
export async function runAgentStream({ url, payload, onEvent, signal }) {
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  })
  if (!resp.ok || !resp.body) {
    throw new Error(`流式请求失败（HTTP ${resp.status}）`)
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let index
    while ((index = buffer.indexOf('\n\n')) >= 0) {
      const frame = buffer.slice(0, index)
      buffer = buffer.slice(index + 2)
      const event = parseFrame(frame)
      if (event) onEvent(event)
    }
  }
}
