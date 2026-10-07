import { useMutation } from '@tanstack/react-query'
import { createContext, useContext } from 'react'

export type User = {
  name: string
  email: string
  provider: 'password' | 'google'
  sub?: string
}

export type LoginData = { email: string; password: string }
export type SignupData = { name: string; email: string; password: string }
export type ConfirmData = { email: string; code: string }
export type PasswordChangeData = { currentPassword: string; newPassword: string }

// Public Cognito ids, baked in at build time (make deploy-auth writes them to .env).
const env = import.meta.env
export const authConfig = {
  userPoolId: env.COGNITO_USER_POOL_ID ?? '',
  clientId: env.COGNITO_CLIENT_ID ?? '',
  domain: env.COGNITO_DOMAIN ?? '',
  googleEnabled: env.COGNITO_GOOGLE_ENABLED === 'true',
}
export const authConfigured = Boolean(authConfig.userPoolId && authConfig.clientId)

export function configureAuth(): void {
  // Hosted UI OAuth 2.0 PKCE flow is configured dynamically via authConfig
}

function cleanDomain(domain: string): string {
  return domain.replace(/^https?:\/\//, '').replace(/\/+$/, '')
}

function generateRandomString(length = 64): string {
  const charset = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~'
  const randomValues = new Uint8Array(length)
  crypto.getRandomValues(randomValues)
  let result = ''
  for (let i = 0; i < length; i++) {
    result += charset[randomValues[i] % charset.length]
  }
  return result
}

function base64UrlEncode(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i])
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

async function generateCodeChallenge(verifier: string): Promise<string> {
  const encoder = new TextEncoder()
  const data = encoder.encode(verifier)
  const digest = await crypto.subtle.digest('SHA-256', data)
  return base64UrlEncode(digest)
}

export function parseJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const parts = token.split('.')
    if (parts.length < 2) return null
    let base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    while (base64.length % 4 !== 0) {
      base64 += '='
    }
    const jsonStr = decodeURIComponent(
      atob(base64)
        .split('')
        .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
        .join(''),
    )
    return JSON.parse(jsonStr) as Record<string, unknown>
  } catch {
    return null
  }
}

export function extractUserFromClaims(claims: Record<string, unknown>): User {
  const email = String(claims.email ?? '')
  const name = String(claims.name ?? (email ? email.split('@')[0] : 'User'))
  const isGoogle =
    Boolean(claims.identities) ||
    (typeof claims.sub === 'string' && claims.sub.includes('Google')) ||
    (Array.isArray(claims.identities) && claims.identities.length > 0)
  return {
    name,
    email,
    provider: isGoogle ? 'google' : 'password',
    sub: claims.sub ? String(claims.sub) : undefined,
  }
}

export function clearTokens(): void {
  localStorage.removeItem('meetings.id_token')
  localStorage.removeItem('meetings.access_token')
  localStorage.removeItem('meetings.refresh_token')
  localStorage.removeItem('meetings.local_user')
  sessionStorage.removeItem('meetings.pkce_verifier')
}

export async function signinRedirect(): Promise<void> {
  if (!authConfigured) return
  const verifier = generateRandomString(64)
  sessionStorage.setItem('meetings.pkce_verifier', verifier)
  const challenge = await generateCodeChallenge(verifier)
  const origin = window.location.origin
  const domain = cleanDomain(authConfig.domain)
  const redirectUri = `${origin}/login`

  const authorizeUrl = `https://${domain}/oauth2/authorize?client_id=${authConfig.clientId}&response_type=code&scope=openid+email+profile&redirect_uri=${encodeURIComponent(redirectUri)}&code_challenge=${challenge}&code_challenge_method=S256`

  window.location.href = authorizeUrl
}

export async function exchangeAuthCode(code: string): Promise<User> {
  const verifier = sessionStorage.getItem('meetings.pkce_verifier') || ''
  const domain = cleanDomain(authConfig.domain)
  const tokenUrl = `https://${domain}/oauth2/token`
  const origin = window.location.origin
  const redirectUri = `${origin}/login`

  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    client_id: authConfig.clientId,
    code,
    redirect_uri: redirectUri,
    code_verifier: verifier,
  })

  const response = await fetch(tokenUrl, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body: body.toString(),
  })

  if (!response.ok) {
    let errorDetail = 'Token exchange failed'
    try {
      const errJson = (await response.json()) as { error?: string; error_description?: string }
      errorDetail = errJson.error_description || errJson.error || errorDetail
    } catch {
      // response body was not JSON
    }
    throw new Error(errorDetail)
  }

  const data = (await response.json()) as {
    id_token?: string
    access_token?: string
    refresh_token?: string
    expires_in?: number
  }

  if (data.id_token) localStorage.setItem('meetings.id_token', data.id_token)
  if (data.access_token) localStorage.setItem('meetings.access_token', data.access_token)
  if (data.refresh_token) localStorage.setItem('meetings.refresh_token', data.refresh_token)
  sessionStorage.removeItem('meetings.pkce_verifier')

  if (!data.id_token) {
    throw new Error('No ID token received from authentication server')
  }

  const claims = parseJwtPayload(data.id_token)
  if (!claims) {
    throw new Error('Failed to parse ID token claims')
  }

  return extractUserFromClaims(claims)
}

export async function refreshTokens(): Promise<string | null> {
  const refreshToken = localStorage.getItem('meetings.refresh_token')
  if (!refreshToken || !authConfigured) return null
  try {
    const domain = cleanDomain(authConfig.domain)
    const tokenUrl = `https://${domain}/oauth2/token`
    const body = new URLSearchParams({
      grant_type: 'refresh_token',
      client_id: authConfig.clientId,
      refresh_token: refreshToken,
    })
    const response = await fetch(tokenUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: body.toString(),
    })
    if (!response.ok) {
      clearTokens()
      return null
    }
    const data = (await response.json()) as {
      id_token?: string
      access_token?: string
    }
    if (data.id_token) localStorage.setItem('meetings.id_token', data.id_token)
    if (data.access_token) localStorage.setItem('meetings.access_token', data.access_token)
    return data.id_token ?? null
  } catch {
    return null
  }
}

export async function signOut(): Promise<void> {
  clearTokens()
  const origin = window.location.origin
  if (authConfigured) {
    const domain = cleanDomain(authConfig.domain)
    const logoutUri = encodeURIComponent(`${origin}/login`)
    window.location.href = `https://${domain}/logout?client_id=${authConfig.clientId}&logout_uri=${logoutUri}`
  } else {
    localStorage.setItem('meetings.local_user', 'null')
    window.location.href = '/login'
  }
}

export class NeedsConfirmationError extends Error {
  readonly email: string

  constructor(email: string) {
    super('Confirm your email first')
    this.email = email
  }
}

const MESSAGES: Record<string, string> = {
  NotAuthorizedException: 'Wrong email or password',
  UserNotFoundException: 'Wrong email or password',
  UsernameExistsException: 'An account with this email already exists',
  AliasExistsException: 'An account with this email already exists',
  CodeMismatchException: 'That code is not right; check the email and try again',
  ExpiredCodeException: 'That code has expired; send a new one',
  LimitExceededException: 'Too many attempts; wait a few minutes and try again',
  TooManyRequestsException: 'Too many attempts; wait a few minutes and try again',
  InvalidPasswordException: 'Use at least 8 characters, with a lowercase letter and a number',
}

function friendly(error: unknown): Error {
  if (error instanceof NeedsConfirmationError) return error
  if (error instanceof Error) return new Error(MESSAGES[error.name] ?? error.message)
  return new Error('Something went wrong')
}

async function withFriendlyErrors<T>(action: () => Promise<T>): Promise<T> {
  try {
    return await action()
  } catch (error) {
    throw friendly(error)
  }
}

const LOCAL_DEV_USER: User = {
  name: 'Demo User',
  email: 'demo@example.com',
  provider: 'password',
}

/** The signed-in user from the stored ID token or local dev user. */
export async function loadUser(): Promise<User | null> {
  if (!authConfigured) {
    const raw = localStorage.getItem('meetings.local_user')
    if (raw === 'null') return null
    return raw ? (JSON.parse(raw) as User) : LOCAL_DEV_USER
  }
  const idToken = await getIdToken()
  if (!idToken) return null
  const claims = parseJwtPayload(idToken)
  if (!claims) return null
  return extractUserFromClaims(claims)
}

/** The ID token the API expects (`Authorization: Bearer ...`). */
export async function getIdToken(): Promise<string | null> {
  if (!authConfigured) return 'local-dev-token'
  const idToken = localStorage.getItem('meetings.id_token')
  if (!idToken) return null
  const claims = parseJwtPayload(idToken)
  if (claims && typeof claims.exp === 'number' && claims.exp * 1000 < Date.now()) {
    return await refreshTokens()
  }
  return idToken
}

export const authApi = {
  login: ({ email, password: _password }: LoginData) =>
    withFriendlyErrors(async () => {
      if (!authConfigured) {
        const user: User = { name: email.split('@')[0] || 'Demo User', email, provider: 'password' }
        localStorage.setItem('meetings.local_user', JSON.stringify(user))
        return user
      }
      throw new Error('Please sign in via Cognito Managed Login')
    }),
  signup: ({ name, email, password: _password }: SignupData) =>
    withFriendlyErrors(async () => {
      if (!authConfigured) {
        const user: User = { name, email, provider: 'password' }
        localStorage.setItem('meetings.local_user', JSON.stringify(user))
        return { needsConfirmation: false }
      }
      throw new Error('Please sign up via Cognito Managed Login')
    }),
  confirm: ({ email: _email, code: _code }: ConfirmData) =>
    withFriendlyErrors(async () => {
      if (!authConfigured) return loadUser()
      throw new Error('Confirmation handled by Cognito Managed Login')
    }),
  resendCode: (_email: string) => withFriendlyErrors(async () => undefined),
  loginWithGoogle: () =>
    withFriendlyErrors(async () => {
      if (!authConfigured) {
        const user: User = {
          name: 'Google User',
          email: 'google-user@example.com',
          provider: 'google',
        }
        localStorage.setItem('meetings.local_user', JSON.stringify(user))
        return user
      }
      await signinRedirect()
      return null
    }),
  updateName: (name: string) =>
    withFriendlyErrors(async () => {
      const user = await loadUser()
      if (user) {
        user.name = name
        if (!authConfigured) {
          localStorage.setItem('meetings.local_user', JSON.stringify(user))
        }
      }
      return user
    }),
  changeEmail: (email: string) =>
    withFriendlyErrors(async () => {
      if (!authConfigured) {
        const user = await loadUser()
        if (user) {
          user.email = email
          localStorage.setItem('meetings.local_user', JSON.stringify(user))
        }
      }
      return { needsConfirmation: false }
    }),
  confirmEmail: (_code: string) =>
    withFriendlyErrors(async () => {
      return loadUser()
    }),
  resendEmailCode: () => withFriendlyErrors(async () => undefined),
  changePassword: async (_data: PasswordChangeData) => {
    // Handled in Cognito Managed Login
  },
}

export type AuthContextValue = {
  /** undefined while the stored session is being checked. */
  user: User | null | undefined
  signIn: (user: User) => void
  signOut: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>')
  return value
}

export function useLogin() {
  const { signIn } = useAuth()
  return useMutation({
    mutationFn: authApi.login,
    onSuccess: (user) => user && signIn(user),
  })
}

export function useSignup() {
  return useMutation({ mutationFn: authApi.signup })
}

export function useConfirmSignup() {
  const { signIn } = useAuth()
  return useMutation({
    mutationFn: authApi.confirm,
    onSuccess: (user) => user && signIn(user),
  })
}

export function useResendCode() {
  return useMutation({ mutationFn: authApi.resendCode })
}

export function useGoogleLogin() {
  return useMutation({ mutationFn: authApi.loginWithGoogle })
}

function useUserUpdate<T>(mutationFn: (input: T) => Promise<User | null>) {
  const { signIn } = useAuth()
  return useMutation({ mutationFn, onSuccess: (user) => user && signIn(user) })
}

export function useUpdateName() {
  return useUserUpdate(authApi.updateName)
}

export function useChangeEmail() {
  return useMutation({ mutationFn: authApi.changeEmail })
}

export function useConfirmEmail() {
  return useUserUpdate(authApi.confirmEmail)
}

export function useResendEmailCode() {
  return useMutation({ mutationFn: authApi.resendEmailCode })
}

export function useChangePassword() {
  return useMutation({ mutationFn: authApi.changePassword })
}
