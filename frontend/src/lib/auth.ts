import { useMutation } from '@tanstack/react-query'
import { Amplify } from 'aws-amplify'
import {
  autoSignIn,
  confirmSignUp,
  confirmUserAttribute,
  fetchAuthSession,
  resendSignUpCode,
  sendUserAttributeVerificationCode,
  signIn,
  signInWithRedirect,
  signUp,
  updatePassword,
  updateUserAttribute,
} from 'aws-amplify/auth'
import { createContext, useContext } from 'react'

export type User = {
  name: string
  email: string
  provider: 'password' | 'google'
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

export function configureAuth() {
  if (!authConfigured) return
  // Cognito only redirects (after Google) to URLs listed in infra/auth.yaml: <origin>/login.
  const redirect = [`${window.location.origin}/login`]
  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId: authConfig.userPoolId,
        userPoolClientId: authConfig.clientId,
        loginWith: {
          email: true,
          ...(authConfig.domain && {
            oauth: {
              domain: authConfig.domain,
              scopes: ['openid', 'email', 'profile'],
              redirectSignIn: redirect,
              redirectSignOut: redirect,
              responseType: 'code',
            },
          }),
        },
      },
    },
  })
}

/** Sign-in succeeded but the email was never verified: the signup page asks for the code. */
export class NeedsConfirmationError extends Error {
  readonly email: string

  constructor(email: string) {
    super('Confirm your email first')
    this.email = email
  }
}

// Cognito's exception names -> messages for people.
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

/** The signed-in user from the (auto-refreshed) ID token, or null. */
export async function loadUser(): Promise<User | null> {
  if (!authConfigured) {
    const raw = localStorage.getItem('meetings.local_user')
    if (raw === 'null') return null
    return raw ? (JSON.parse(raw) as User) : LOCAL_DEV_USER
  }
  try {
    const claims = (await fetchAuthSession()).tokens?.idToken?.payload
    if (!claims) return null
    const email = String(claims.email ?? '')
    return {
      name: String(claims.name ?? email.split('@')[0]),
      email,
      // Federated (Google) accounts carry an "identities" claim.
      provider: claims.identities ? 'google' : 'password',
    }
  } catch {
    return null
  }
}

/** The ID token the API expects (`Authorization: Bearer ...`); Amplify refreshes it. */
export async function getIdToken(): Promise<string | null> {
  if (!authConfigured) return 'local-dev-token'
  try {
    return (await fetchAuthSession()).tokens?.idToken?.toString() ?? null
  } catch {
    return null
  }
}

/** Fresh tokens, so the new name or email reaches the API (it copies them from the ID token). */
async function reloadUser(): Promise<User | null> {
  await fetchAuthSession({ forceRefresh: true })
  return loadUser()
}

export const authApi = {
  login: ({ email, password }: LoginData) =>
    withFriendlyErrors(async () => {
      if (!authConfigured) {
        const user: User = { name: email.split('@')[0] || 'Demo User', email, provider: 'password' }
        localStorage.setItem('meetings.local_user', JSON.stringify(user))
        return user
      }
      const { nextStep } = await signIn({ username: email, password })
      if (nextStep.signInStep === 'CONFIRM_SIGN_UP') throw new NeedsConfirmationError(email)
      if (nextStep.signInStep !== 'DONE') throw new Error(`Unsupported sign-in step`)
      return loadUser()
    }),
  /** Creates the account; Cognito emails a code that `confirm` checks. */
  signup: ({ name, email, password }: SignupData) =>
    withFriendlyErrors(async () => {
      if (!authConfigured) {
        const user: User = { name, email, provider: 'password' }
        localStorage.setItem('meetings.local_user', JSON.stringify(user))
        return { needsConfirmation: false }
      }
      const { nextStep } = await signUp({
        username: email,
        password,
        options: { userAttributes: { email, name }, autoSignIn: true },
      })
      return { needsConfirmation: nextStep.signUpStep === 'CONFIRM_SIGN_UP' }
    }),
  /** Verifies the email. Signs in straight away if the password is still known (same visit). */
  confirm: ({ email, code }: ConfirmData) =>
    withFriendlyErrors(async () => {
      const { nextStep } = await confirmSignUp({ username: email, confirmationCode: code })
      if (nextStep.signUpStep !== 'COMPLETE_AUTO_SIGN_IN') return null
      await autoSignIn()
      return loadUser()
    }),
  resendCode: (email: string) =>
    withFriendlyErrors(() => resendSignUpCode({ username: email }).then(() => undefined)),
  /** Leaves the page for Google; the user comes back signed in on /login. */
  loginWithGoogle: () => withFriendlyErrors(() => signInWithRedirect({ provider: 'Google' })),

  // Profile changes (password accounts only: Google sets the name and email on every sign-in).
  updateName: (name: string) =>
    withFriendlyErrors(async () => {
      await updateUserAttribute({ userAttribute: { attributeKey: 'name', value: name } })
      return reloadUser()
    }),
  /** Cognito emails a code to the new address; the email changes once `confirmEmail` checks it. */
  changeEmail: (email: string) =>
    withFriendlyErrors(async () => {
      const { nextStep } = await updateUserAttribute({
        userAttribute: { attributeKey: 'email', value: email },
      })
      return { needsConfirmation: nextStep.updateAttributeStep === 'CONFIRM_ATTRIBUTE_WITH_CODE' }
    }),
  confirmEmail: (code: string) =>
    withFriendlyErrors(async () => {
      await confirmUserAttribute({ userAttributeKey: 'email', confirmationCode: code })
      return reloadUser()
    }),
  resendEmailCode: () =>
    withFriendlyErrors(() =>
      sendUserAttributeVerificationCode({ userAttributeKey: 'email' }).then(() => undefined),
    ),
  changePassword: async ({ currentPassword, newPassword }: PasswordChangeData) => {
    try {
      await updatePassword({ oldPassword: currentPassword, newPassword })
    } catch (error) {
      // Here it means the current password is wrong, not the email.
      if (error instanceof Error && error.name === 'NotAuthorizedException') {
        throw new Error('Current password is wrong')
      }
      throw friendly(error)
    }
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

/** Puts the updated user (from the refreshed token) into the auth state. */
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
