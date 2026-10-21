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

export function useAgentApi(api, pluginId) {
  const base = `plugin/${pluginId}`

  const call = (method, path, body) => {
    const fn = api && api[method]
    if (typeof fn !== 'function') {
      return Promise.reject(new Error(`注入的 api 对象不支持 ${method} 方法`))
    }
    return Promise.resolve(fn.call(api, path, body)).then(unwrap)
  }

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
