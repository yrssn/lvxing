const TOKEN_KEY = 'lvx_token'
const USER_KEY = 'lvx_username'
const ADMIN_KEY = 'lvx_is_admin'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function getUsername() {
  return localStorage.getItem(USER_KEY) || ''
}

export function isAdmin() {
  return localStorage.getItem(ADMIN_KEY) === '1'
}

export function setAuth(token, username, admin) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, username)
  localStorage.setItem(ADMIN_KEY, admin ? '1' : '0')
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
  localStorage.removeItem(ADMIN_KEY)
}
