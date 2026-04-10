'use client'

const TOKEN_KEY = 'finanalyse_token'

export function saveToken(token: string): void {
  if (typeof window === 'undefined') return
  localStorage.setItem(TOKEN_KEY, token)
}

export function getToken(): string | null {
  if (typeof window === 'undefined') return null
  return localStorage.getItem(TOKEN_KEY)
}

export function removeToken(): void {
  if (typeof window === 'undefined') return
  localStorage.removeItem(TOKEN_KEY)
}

export function isLoggedIn(): boolean {
  return !!getToken()
}

/**
 * Parse ?token= from URL after Google OAuth callback.
 * Saves token to localStorage and strips it from the URL.
 * Returns true if a token was found and saved.
 */
export function handleAuthCallback(): boolean {
  if (typeof window === 'undefined') return false
  const params = new URLSearchParams(window.location.search)
  const token = params.get('token')
  if (token) {
    saveToken(token)
    window.history.replaceState({}, '', window.location.pathname)
    return true
  }
  return false
}

export interface UserInfo {
  email: string
  name?: string
}

/**
 * Decode basic info from a JWT payload (no verification - display only).
 */
export function decodeTokenPayload(token: string): UserInfo | null {
  try {
    const parts = token.split('.')
    if (parts.length !== 3) return null
    const payload = JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')))
    return {
      email: payload.email || payload.sub || 'User',
      name: payload.name,
    }
  } catch {
    return null
  }
}
