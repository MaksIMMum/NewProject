import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type ReactNode } from 'react'

import { AuthContext, loadUser, signOut as authSignOut, type User } from '@/lib/auth'

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [user, setUser] = useState<User | null | undefined>(undefined)

  useEffect(() => {
    let active = true
    const refresh = () => {
      loadUser().then((next) => {
        if (active) setUser(next)
      })
    }
    refresh()

    const onStorage = (e: StorageEvent) => {
      if (
        e.key === 'meetings.id_token' ||
        e.key === 'meetings.local_user' ||
        e.key === 'meetings.access_token'
      ) {
        refresh()
      }
    }

    window.addEventListener('storage', onStorage)
    return () => {
      active = false
      window.removeEventListener('storage', onStorage)
    }
  }, [])

  const signIn = (next: User) => setUser(next)
  const signOut = async () => {
    setUser(null)
    queryClient.clear()
    await authSignOut()
  }

  return <AuthContext value={{ user, signIn, signOut }}>{children}</AuthContext>
}
