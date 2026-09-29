import { useQueryClient } from '@tanstack/react-query'
import { Hub } from 'aws-amplify/utils'
import { signOut as cognitoSignOut } from 'aws-amplify/auth'
import { useEffect, useState, type ReactNode } from 'react'

import { AuthContext, authConfigured, loadUser, type User } from '@/lib/auth'

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [user, setUser] = useState<User | null | undefined>(undefined)

  useEffect(() => {
    let active = true
    const refresh = () => loadUser().then((next) => active && setUser(next))
    refresh()

    if (!authConfigured) {
      return () => {
        active = false
      }
    }

    // Keeps the state in step with Cognito: the Google redirect, sign-out in another place
    // (e.g. a 401 from the API), or a refresh token that no longer works.
    const stop = Hub.listen('auth', ({ payload }) => {
      if (payload.event === 'signedIn' || payload.event === 'signInWithRedirect') refresh()
      if (payload.event === 'signedOut' || payload.event === 'tokenRefresh_failure') {
        setUser(null)
        // The next user must not see this user's cached meetings.
        queryClient.clear()
      }
    })
    return () => {
      active = false
      stop()
    }
  }, [queryClient])

  const signIn = (next: User) => setUser(next)
  const signOut = async () => {
    if (authConfigured) {
      await cognitoSignOut().catch(() => undefined)
    } else {
      localStorage.setItem('meetings.local_user', 'null')
    }
    setUser(null)
    queryClient.clear()
  }

  return <AuthContext value={{ user, signIn, signOut }}>{children}</AuthContext>
}
