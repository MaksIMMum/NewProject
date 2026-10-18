import { signOut } from 'aws-amplify/auth'

import { getIdToken } from '@/lib/auth'

export type Participant = {
  id: string
  name: string
  email: string
}

export type AgendaItem = {
  topic: string
  owner: string | null
  minutes: number | null
}

export type ActionItem = {
  task: string
  owner: string | null
  due: string | null
}

export type ParsedAgenda = {
  title: string | null
  starts_at: string | null
  duration_minutes: number | null
  items: AgendaItem[]
  action_items: ActionItem[]
  language: string
}

export type AiSuggestion = {
  model: string
  prompt_version: string
  raw_text?: string
  agenda: ParsedAgenda
}

export type Meeting = {
  id: string
  title: string
  description: string
  starts_at: string
  ends_at: string
  place: string
  participants: Participant[]
  agenda?: ParsedAgenda | null
  ai_suggestion?: AiSuggestion | null
  created_at: string
}

export type MeetingCreate = {
  title: string
  description: string
  starts_at: string
  ends_at: string
  place: string
  participant_ids: string[]
}

export type ParticipantCreate = {
  name: string
  email: string
}

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// Backend origin, set at build time for AWS (the Lambda function URL). Empty locally,
// where the Vite dev server or nginx proxies /api to the backend.
const API_URL = (import.meta.env.VITE_API_URL ?? '').replace(/\/+$/, '')
const AI_URL = (import.meta.env.VITE_AI_URL ?? '').replace(/\/+$/, '')

type ValidationIssue = { loc?: (string | number)[]; msg: string }

function errorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return (detail as ValidationIssue[])
      .map((issue) => {
        const field = issue.loc?.filter((part) => part !== 'body').join('.')
        const msg = issue.msg.replace(/^Value error, /, '')
        return field ? `${field}: ${msg}` : msg
      })
      .join('; ')
  }
  return fallback
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = await getIdToken()
  const response = await fetch(`${API_URL}/api${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token && { Authorization: `Bearer ${token}` }),
      ...init?.headers,
    },
  })

  // The session is gone (revoked, or the refresh token expired): sign out, which sends the
  // user back to the login page (see AuthProvider).
  if (response.status === 401) await signOut().catch(() => undefined)

  if (!response.ok) {
    let detail: unknown
    try {
      detail = (await response.json()).detail
    } catch {
      // body was not JSON
    }
    throw new ApiError(response.status, errorMessage(detail, response.statusText))
  }

  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const api = {
  listMeetings: () => request<Meeting[]>('/meetings'),
  createMeeting: (data: MeetingCreate) =>
    request<Meeting>('/meetings', { method: 'POST', body: JSON.stringify(data) }),
  updateMeeting: ({ id, ...data }: MeetingCreate & { id: string }) =>
    request<Meeting>(`/meetings/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteMeeting: (id: string) => request<void>(`/meetings/${id}`, { method: 'DELETE' }),
  listParticipants: () => request<Participant[]>('/participants'),
  createParticipant: (data: ParticipantCreate) =>
    request<Participant>('/participants', { method: 'POST', body: JSON.stringify(data) }),
  parseAgenda: async (
    payload: { text: string; today: string; tz: string },
    signal?: AbortSignal,
  ): Promise<{ agenda: ParsedAgenda; model: string; prompt_version: string }> => {
    const token = await getIdToken()
    const targetUrl = AI_URL || '/api/ai/parse'
    const response = await fetch(targetUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token && { Authorization: `Bearer ${token}` }),
      },
      body: JSON.stringify(payload),
      signal,
    })
    if (!response.ok) {
      let detail: unknown
      try {
        const body = await response.json()
        detail = body.error ?? body.detail
      } catch {
        // response body was not JSON
      }
      throw new ApiError(
        response.status,
        (typeof detail === 'string' ? detail : '') ||
          response.statusText ||
          'Failed to parse agenda',
      )
    }
    return response.json()
  },
  saveAgenda: (
    meetingId: string,
    data: { agenda: ParsedAgenda; ai_suggestion?: AiSuggestion | null },
  ) =>
    request<Meeting>(`/meetings/${meetingId}/agenda`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  deleteAgenda: (meetingId: string) =>
    request<Meeting>(`/meetings/${meetingId}/agenda`, {
      method: 'DELETE',
    }),
}
