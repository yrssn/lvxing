import { getToken, clearAuth } from '../composables/auth'
import router from '../router'

/**
 * fetch 封装：自动带 Bearer token、统一解析 {success,data,message}、401 跳登录
 */
export async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) }
  if (options.body != null && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json'
  }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`

  let resp
  try {
    resp = await fetch(path, { ...options, headers })
  } catch (e) {
    throw new Error('网络异常：' + e.message)
  }

  if (resp.status === 401) {
    clearAuth()
    router.push('/login')
    throw new Error('登录已过期，请重新登录')
  }

  let json = null
  try {
    json = await resp.json()
  } catch {
    /* 非 JSON 响应 */
  }
  if (!resp.ok) {
    throw new Error(json?.detail || json?.message || `请求失败 (${resp.status})`)
  }
  return json
}

export function get(path) {
  return request(path)
}

export function post(path, body) {
  return request(path, { method: 'POST', body: JSON.stringify(body ?? {}) })
}

export function put(path, body) {
  return request(path, { method: 'PUT', body: JSON.stringify(body ?? {}) })
}

export function del(path) {
  return request(path, { method: 'DELETE' })
}
