import { useEffect, useRef, useState } from 'react'
import {
  AlertCircleIcon,
  CheckCircle2Icon,
  ClockIcon,
  ListTodoIcon,
  Loader2Icon,
  PlusIcon,
  SparklesIcon,
  Trash2Icon,
  XCircleIcon,
} from 'lucide-react'
import { toast } from 'sonner'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { useCreateMeeting, useSaveAgenda } from '@/hooks/queries'
import { type ActionItem, type AgendaItem, api, type Meeting, type ParsedAgenda } from '@/lib/api'

function parseMeetingStartsAt(startsAt: string | null | undefined): Date {
  if (!startsAt) return new Date()
  const d = new Date(startsAt)
  if (!isNaN(d.getTime())) return d

  const timeMatch = startsAt.match(/^(\d{1,2}):(\d{2})/)
  if (timeMatch) {
    const now = new Date()
    now.setHours(parseInt(timeMatch[1], 10), parseInt(timeMatch[2], 10), 0, 0)
    return now
  }
  return new Date()
}

type Props = {
  meeting: Meeting | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function PasteAgendaDialog({ meeting, open, onOpenChange }: Props) {
  const [step, setStep] = useState<'paste' | 'form'>('paste')
  const [rawText, setRawText] = useState('')
  const [isParsing, setIsParsing] = useState(false)
  const [parseError, setParseError] = useState<string | null>(null)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)

  // AbortController reference for canceling the LLM request
  const abortControllerRef = useRef<AbortController | null>(null)
  const timerRef = useRef<number | null>(null)

  // The parsed agenda form state
  const [agenda, setAgenda] = useState<ParsedAgenda>({
    title: '',
    starts_at: null,
    duration_minutes: null,
    items: [],
    action_items: [],
    language: 'en',
  })

  // The original AI suggestion (saved alongside user corrections for quality tracking)
  const [aiMetadata, setAiMetadata] = useState<{
    model: string
    prompt_version: string
    raw_suggestion: ParsedAgenda
  } | null>(null)

  // Tracking touched/edited fields to clear the "suggested" badges
  const [touchedFields, setTouchedFields] = useState<Set<string>>(new Set())

  const createMeetingMutation = useCreateMeeting()
  const saveAgendaMutation = useSaveAgenda()
  const [isSaving, setIsSaving] = useState(false)

  // Reset or initialize when opened
  useEffect(() => {
    if (!open) return

    if (meeting?.agenda) {
      setAgenda(meeting.agenda)
      setStep('form')
      setTouchedFields(new Set(['all']))
    } else {
      setAgenda({
        title: '',
        starts_at: null,
        duration_minutes: null,
        items: [],
        action_items: [],
        language: 'en',
      })
      setAiMetadata(null)
      setStep('paste')
      setRawText('')
      setParseError(null)
      setTouchedFields(new Set())
    }
  }, [open, meeting])

  const markTouched = (fieldKey: string) => {
    setTouchedFields((prev) => new Set(prev).add(fieldKey))
  }

  const handleParse = async () => {
    const trimmed = rawText.trim()
    if (!trimmed) {
      setParseError('Please paste some text first.')
      return
    }
    if (trimmed.length > 10000) {
      setParseError('Text is too long (maximum 10,000 characters).')
      return
    }

    setParseError(null)
    setIsParsing(true)
    setElapsedSeconds(0)

    const controller = new AbortController()
    abortControllerRef.current = controller

    timerRef.current = window.setInterval(() => {
      setElapsedSeconds((prev) => prev + 1)
    }, 1000)

    try {
      const todayIso = new Date().toISOString().split('T')[0]
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'

      const result = await api.parseAgenda(
        { text: trimmed, today: todayIso, tz },
        controller.signal,
      )

      if (timerRef.current) window.clearInterval(timerRef.current)
      setIsParsing(false)

      // Initialize form with parsed results
      setAgenda(result.agenda)
      setAiMetadata({
        model: result.model,
        prompt_version: result.prompt_version,
        raw_suggestion: result.agenda,
      })
      setTouchedFields(new Set()) // All fresh AI suggestions show badge
      setStep('form')
      toast.success('Agenda parsed successfully!')
    } catch (err: unknown) {
      if (timerRef.current) window.clearInterval(timerRef.current)
      setIsParsing(false)

      if (err instanceof Error && err.name === 'AbortError') {
        toast.info('Parsing cancelled')
      } else {
        const message = err instanceof Error ? err.message : 'Failed to parse agenda'
        setParseError(message)
        toast.error(message)
      }
    }
  }

  const handleCancelParse = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }
    if (timerRef.current) {
      window.clearInterval(timerRef.current)
      timerRef.current = null
    }
    setIsParsing(false)
    setElapsedSeconds(0)
  }

  const handleSave = async () => {
    try {
      setIsSaving(true)
      const aiPayload = aiMetadata
        ? {
            model: aiMetadata.model,
            prompt_version: aiMetadata.prompt_version,
            raw_text: rawText,
            agenda: aiMetadata.raw_suggestion,
          }
        : (meeting?.ai_suggestion ?? null)

      if (meeting) {
        await saveAgendaMutation.mutateAsync({
          meetingId: meeting.id,
          agenda,
          ai_suggestion: aiPayload,
        })
        toast.success('Agenda saved to meeting')
      } else {
        const startsAtDate = parseMeetingStartsAt(agenda.starts_at)
        const durationMin =
          agenda.duration_minutes && agenda.duration_minutes > 0 ? agenda.duration_minutes : 45
        const endsAtDate = new Date(startsAtDate.getTime() + durationMin * 60000)

        const created = await createMeetingMutation.mutateAsync({
          title: agenda.title?.trim() || 'Team Sync',
          description: `Agenda parsed with ${aiMetadata?.model || 'Claude'}`,
          starts_at: startsAtDate.toISOString(),
          ends_at: endsAtDate.toISOString(),
          place: 'Online',
          participant_ids: [],
        })

        await saveAgendaMutation.mutateAsync({
          meetingId: created.id,
          agenda,
          ai_suggestion: aiPayload,
        })
        toast.success('Meeting created with agenda')
      }
      onOpenChange(false)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to save agenda'
      toast.error(message)
    } finally {
      setIsSaving(false)
    }
  }

  // Agenda item handlers
  const updateItem = (index: number, patch: Partial<AgendaItem>, fieldKey: string) => {
    markTouched(fieldKey)
    setAgenda((prev) => {
      const items = [...prev.items]
      items[index] = { ...items[index], ...patch }
      return { ...prev, items }
    })
  }

  const addItem = () => {
    setAgenda((prev) => ({
      ...prev,
      items: [...prev.items, { topic: '', owner: null, minutes: null }],
    }))
  }

  const removeItem = (index: number) => {
    setAgenda((prev) => ({
      ...prev,
      items: prev.items.filter((_, i) => i !== index),
    }))
  }

  // Action item handlers
  const updateActionItem = (index: number, patch: Partial<ActionItem>, fieldKey: string) => {
    markTouched(fieldKey)
    setAgenda((prev) => {
      const actions = [...prev.action_items]
      actions[index] = { ...actions[index], ...patch }
      return { ...prev, action_items: actions }
    })
  }

  const addActionItem = () => {
    setAgenda((prev) => ({
      ...prev,
      action_items: [...prev.action_items, { task: '', owner: null, due: null }],
    }))
  }

  const removeActionItem = (index: number) => {
    setAgenda((prev) => ({
      ...prev,
      action_items: prev.action_items.filter((_, i) => i !== index),
    }))
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) {
          handleCancelParse()
        }
        onOpenChange(nextOpen)
      }}
    >
      <DialogContent className="max-h-[calc(100svh-2rem)] grid-rows-[auto_minmax(0,1fr)_auto] sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-2xl">
            <SparklesIcon className="size-5 text-primary" />
            {step === 'paste'
              ? 'Paste an agenda'
              : meeting
                ? 'Review & save agenda'
                : 'Review & create meeting'}
          </DialogTitle>
          <DialogDescription>
            {step === 'paste'
              ? 'Paste an email, chat message, or notes. Claude will extract topics, owners, durations, and action items.'
              : meeting
                ? 'Check the AI-suggested fields, make any corrections, and save to your meeting.'
                : 'Check the AI-suggested fields, make any corrections, and create your meeting.'}
          </DialogDescription>
        </DialogHeader>

        <div className="-mx-6 overflow-y-auto px-6 py-2">
          {step === 'paste' ? (
            <div className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <Textarea
                  placeholder={`Пн 10:00, синк по прайсингу, 45 хв.\n1) нові тарифи Pro — Олена, 15 хв\n2) фідбек від клієнтів — Taras\n3) що робимо з річною знижкою.\nTaras до п'ятниці збирає порівняння з конкурентами.`}
                  value={rawText}
                  onChange={(e) => setRawText(e.target.value)}
                  disabled={isParsing}
                  rows={8}
                  className="font-mono text-sm leading-relaxed"
                />
                <div className="flex justify-between text-xs text-muted-foreground">
                  <span>Emails, chat logs, or meeting notes</span>
                  <span className={rawText.length > 10000 ? 'text-destructive font-semibold' : ''}>
                    {rawText.length.toLocaleString()} / 10,000 chars
                  </span>
                </div>
              </div>

              {parseError && (
                <Alert variant="destructive">
                  <AlertCircleIcon className="size-4" />
                  <AlertDescription>{parseError}</AlertDescription>
                </Alert>
              )}

              {isParsing && (
                <div className="flex items-center justify-between rounded-lg border border-primary/20 bg-primary/5 p-4">
                  <div className="flex items-center gap-3">
                    <Loader2Icon className="size-5 animate-spin text-primary" />
                    <div className="flex flex-col">
                      <span className="text-sm font-medium">Parsing agenda with Claude...</span>
                      <span className="text-xs text-muted-foreground">
                        Extracting structured items ({elapsedSeconds}s elapsed)
                      </span>
                    </div>
                  </div>
                  <Button variant="outline" size="sm" onClick={handleCancelParse}>
                    <XCircleIcon className="size-4" />
                    Cancel
                  </Button>
                </div>
              )}
            </div>
          ) : (
            <div className="flex flex-col gap-6">
              {/* Meeting title suggestion */}
              <div className="flex flex-col gap-1.5">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Meeting Title
                  </label>
                  {!touchedFields.has('title') && agenda.title && (
                    <Badge variant="secondary" className="text-[10px]">
                      suggested
                    </Badge>
                  )}
                </div>
                <Input
                  value={agenda.title ?? ''}
                  onChange={(e) => {
                    markTouched('title')
                    setAgenda((prev) => ({ ...prev, title: e.target.value }))
                  }}
                  placeholder="Meeting Title"
                />
              </div>

              {/* Timing & duration */}
              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1.5">
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      Start Time
                    </label>
                    {!touchedFields.has('starts_at') && agenda.starts_at && (
                      <Badge variant="secondary" className="text-[10px]">
                        suggested
                      </Badge>
                    )}
                  </div>
                  <Input
                    value={agenda.starts_at ?? ''}
                    onChange={(e) => {
                      markTouched('starts_at')
                      setAgenda((prev) => ({ ...prev, starts_at: e.target.value }))
                    }}
                    placeholder="e.g. 10:00"
                  />
                </div>

                <div className="flex flex-col gap-1.5">
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      Duration (min)
                    </label>
                    {!touchedFields.has('duration') && agenda.duration_minutes !== null && (
                      <Badge variant="secondary" className="text-[10px]">
                        suggested
                      </Badge>
                    )}
                  </div>
                  <Input
                    type="number"
                    value={agenda.duration_minutes ?? ''}
                    onChange={(e) => {
                      markTouched('duration')
                      setAgenda((prev) => ({
                        ...prev,
                        duration_minutes: e.target.value ? Number(e.target.value) : null,
                      }))
                    }}
                    placeholder="45"
                  />
                </div>
              </div>

              {/* Agenda items */}
              <div className="flex flex-col gap-3">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-1.5 text-sm font-semibold">
                    <ClockIcon className="size-4" />
                    Agenda Topics ({agenda.items.length})
                  </span>
                  <Button variant="ghost" size="sm" onClick={addItem}>
                    <PlusIcon className="size-3.5" />
                    Add topic
                  </Button>
                </div>

                {agenda.items.length === 0 ? (
                  <p className="rounded-md border border-dashed p-4 text-center text-xs text-muted-foreground">
                    No agenda topics found. Click &quot;Add topic&quot; to add one.
                  </p>
                ) : (
                  <div className="flex flex-col gap-2.5">
                    {agenda.items.map((item, idx) => (
                      <div
                        key={idx}
                        className="flex items-start gap-2 rounded-lg border bg-card p-3 text-sm shadow-xs"
                      >
                        <div className="flex flex-1 flex-col gap-2">
                          <div className="flex items-center gap-2">
                            <Input
                              value={item.topic}
                              onChange={(e) =>
                                updateItem(idx, { topic: e.target.value }, `item-${idx}-topic`)
                              }
                              placeholder="Topic name"
                              className="font-medium"
                            />
                            {!touchedFields.has(`item-${idx}-topic`) && item.topic && (
                              <Badge variant="secondary" className="shrink-0 text-[10px]">
                                suggested
                              </Badge>
                            )}
                          </div>

                          <div className="grid grid-cols-2 gap-2">
                            <div className="flex items-center gap-1">
                              <Input
                                value={item.owner ?? ''}
                                onChange={(e) =>
                                  updateItem(
                                    idx,
                                    { owner: e.target.value || null },
                                    `item-${idx}-owner`,
                                  )
                                }
                                placeholder="Owner (e.g. Olena)"
                                className="h-8 text-xs"
                              />
                              {!touchedFields.has(`item-${idx}-owner`) && item.owner && (
                                <Badge variant="secondary" className="shrink-0 text-[9px]">
                                  suggested
                                </Badge>
                              )}
                            </div>

                            <div className="flex items-center gap-1">
                              <Input
                                type="number"
                                value={item.minutes ?? ''}
                                onChange={(e) =>
                                  updateItem(
                                    idx,
                                    { minutes: e.target.value ? Number(e.target.value) : null },
                                    `item-${idx}-minutes`,
                                  )
                                }
                                placeholder="Minutes (e.g. 15)"
                                className="h-8 text-xs"
                              />
                              {!touchedFields.has(`item-${idx}-minutes`) &&
                                item.minutes !== null && (
                                  <Badge variant="secondary" className="shrink-0 text-[9px]">
                                    suggested
                                  </Badge>
                                )}
                            </div>
                          </div>
                        </div>

                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => removeItem(idx)}
                          className="size-8 text-muted-foreground hover:text-destructive"
                        >
                          <Trash2Icon className="size-4" />
                        </Button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Action items */}
              <div className="flex flex-col gap-3">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-1.5 text-sm font-semibold">
                    <ListTodoIcon className="size-4" />
                    Action Items ({agenda.action_items.length})
                  </span>
                  <Button variant="ghost" size="sm" onClick={addActionItem}>
                    <PlusIcon className="size-3.5" />
                    Add task
                  </Button>
                </div>

                {agenda.action_items.length === 0 ? (
                  <p className="rounded-md border border-dashed p-4 text-center text-xs text-muted-foreground">
                    No action items or assigned deliverables found.
                  </p>
                ) : (
                  <div className="flex flex-col gap-2.5">
                    {agenda.action_items.map((action, idx) => (
                      <div
                        key={idx}
                        className="flex items-start gap-2 rounded-lg border bg-card p-3 text-sm shadow-xs"
                      >
                        <div className="flex flex-1 flex-col gap-2">
                          <div className="flex items-center gap-2">
                            <Input
                              value={action.task}
                              onChange={(e) =>
                                updateActionItem(idx, { task: e.target.value }, `act-${idx}-task`)
                              }
                              placeholder="Action item task"
                            />
                            {!touchedFields.has(`act-${idx}-task`) && action.task && (
                              <Badge variant="secondary" className="shrink-0 text-[10px]">
                                suggested
                              </Badge>
                            )}
                          </div>

                          <div className="grid grid-cols-2 gap-2">
                            <div className="flex items-center gap-1">
                              <Input
                                value={action.owner ?? ''}
                                onChange={(e) =>
                                  updateActionItem(
                                    idx,
                                    { owner: e.target.value || null },
                                    `act-${idx}-owner`,
                                  )
                                }
                                placeholder="Assignee (e.g. Taras)"
                                className="h-8 text-xs"
                              />
                              {!touchedFields.has(`act-${idx}-owner`) && action.owner && (
                                <Badge variant="secondary" className="shrink-0 text-[9px]">
                                  suggested
                                </Badge>
                              )}
                            </div>

                            <div className="flex items-center gap-1">
                              <Input
                                type="date"
                                value={action.due ?? ''}
                                onChange={(e) =>
                                  updateActionItem(
                                    idx,
                                    { due: e.target.value || null },
                                    `act-${idx}-due`,
                                  )
                                }
                                className="h-8 text-xs"
                              />
                              {!touchedFields.has(`act-${idx}-due`) && action.due && (
                                <Badge variant="secondary" className="shrink-0 text-[9px]">
                                  suggested
                                </Badge>
                              )}
                            </div>
                          </div>
                        </div>

                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => removeActionItem(idx)}
                          className="size-8 text-muted-foreground hover:text-destructive"
                        >
                          <Trash2Icon className="size-4" />
                        </Button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        <DialogFooter className="sm:justify-between">
          {step === 'paste' ? (
            <>
              <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={isParsing}>
                Cancel
              </Button>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  onClick={() => {
                    setStep('form')
                    setTouchedFields(new Set(['manual']))
                  }}
                  disabled={isParsing}
                >
                  Type manually
                </Button>
                <Button onClick={handleParse} disabled={isParsing || !rawText.trim()}>
                  {isParsing ? (
                    <>
                      <Loader2Icon className="size-4 animate-spin" />
                      Parsing...
                    </>
                  ) : (
                    <>
                      <SparklesIcon className="size-4" />
                      Parse with AI
                    </>
                  )}
                </Button>
              </div>
            </>
          ) : (
            <>
              <Button variant="ghost" onClick={() => setStep('paste')}>
                Re-paste text
              </Button>
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => onOpenChange(false)}>
                  Cancel
                </Button>
                <Button
                  onClick={handleSave}
                  disabled={
                    isSaving || saveAgendaMutation.isPending || createMeetingMutation.isPending
                  }
                >
                  {isSaving || saveAgendaMutation.isPending || createMeetingMutation.isPending ? (
                    <>
                      <Loader2Icon className="size-4 animate-spin" />
                      {meeting ? 'Saving...' : 'Creating meeting...'}
                    </>
                  ) : (
                    <>
                      <CheckCircle2Icon className="size-4" />
                      {meeting ? 'Save agenda' : 'Create meeting'}
                    </>
                  )}
                </Button>
              </div>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
