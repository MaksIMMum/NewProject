import { useRef, useState } from 'react'
import {
  CheckCircle2Icon,
  ClockIcon,
  ListTodoIcon,
  MapPinIcon,
  PencilIcon,
  SparklesIcon,
  Trash2Icon,
  UsersIcon,
} from 'lucide-react'
import { toast } from 'sonner'

import { PasteAgendaDialog } from '@/components/paste-agenda-dialog'
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
import { useDeleteAgenda } from '@/hooks/queries'
import type { Meeting } from '@/lib/api'
import { formatWhen } from '@/lib/format'

function isUrl(value: string): boolean {
  return /^https?:\/\/\S+$/.test(value)
}

type Props = {
  meeting: Meeting | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onEdit: (meeting: Meeting) => void
  onDelete: (meeting: Meeting) => void
}

export function MeetingDetailsDialog({ meeting, open, onOpenChange, onEdit, onDelete }: Props) {
  const editButtonRef = useRef<HTMLButtonElement>(null)
  const [agendaOpen, setAgendaOpen] = useState(false)
  const deleteAgendaMutation = useDeleteAgenda()

  return (
    <>
      <Dialog open={open && meeting !== null} onOpenChange={onOpenChange}>
        <DialogContent
          className="max-h-[calc(100svh-2rem)] grid-rows-[auto_minmax(0,1fr)_auto] sm:max-w-lg"
          // Radix would focus the first button (Delete); start on Edit instead.
          onOpenAutoFocus={(event) => {
            event.preventDefault()
            editButtonRef.current?.focus()
          }}
        >
          {meeting && (
            <>
              <DialogHeader>
                <DialogTitle className="pr-8 text-3xl leading-tight">{meeting.title}</DialogTitle>
                <DialogDescription className="flex items-center gap-2">
                  <ClockIcon className="size-4 shrink-0" />
                  {formatWhen(meeting)}
                </DialogDescription>
              </DialogHeader>

              <div className="-mx-6 flex flex-col gap-5 overflow-y-auto px-6">
                <div className="flex items-start gap-2">
                  <MapPinIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                  {isUrl(meeting.place) ? (
                    <a
                      href={meeting.place}
                      target="_blank"
                      rel="noreferrer"
                      className="break-all underline underline-offset-4 hover:text-hover"
                    >
                      {meeting.place}
                    </a>
                  ) : (
                    <span className="break-words">{meeting.place}</span>
                  )}
                </div>

                {meeting.description && (
                  <>
                    <div className="hairline" />
                    <p className="font-serif text-lg leading-snug whitespace-pre-line">
                      {meeting.description}
                    </p>
                  </>
                )}

                <div className="hairline" />
                <div className="flex flex-col gap-3">
                  <h3 className="flex items-center gap-2 text-lg">
                    <UsersIcon className="size-4" />
                    Participants
                    <span className="font-sans text-sm text-muted-foreground">
                      {meeting.participants.length}
                    </span>
                  </h3>
                  {meeting.participants.length === 0 ? (
                    <p className="text-muted-foreground">No participants yet.</p>
                  ) : (
                    <ul className="flex flex-col gap-2">
                      {meeting.participants.map((p) => (
                        <li key={p.id} className="flex flex-wrap items-baseline gap-x-2">
                          <span className="font-semibold">{p.name}</span>
                          <a
                            href={`mailto:${p.email}`}
                            className="text-sm text-muted-foreground hover:text-hover"
                          >
                            {p.email}
                          </a>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                <div className="hairline" />
                {/* Agenda & Action Items Section */}
                <div className="flex flex-col gap-3">
                  <div className="flex items-center justify-between">
                    <h3 className="flex items-center gap-2 text-lg">
                      <ListTodoIcon className="size-4" />
                      Agenda & Actions
                      {meeting.agenda && (
                        <span className="font-sans text-sm text-muted-foreground">
                          {(meeting.agenda.items?.length || 0) +
                            (meeting.agenda.action_items?.length || 0)}
                        </span>
                      )}
                    </h3>
                    <div className="flex items-center gap-2">
                      {meeting.agenda && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 text-xs text-muted-foreground hover:text-destructive"
                          onClick={() => {
                            if (window.confirm('Are you sure you want to delete this agenda?')) {
                              deleteAgendaMutation.mutate(meeting.id, {
                                onSuccess: () => toast.success('Agenda removed'),
                                onError: (err) =>
                                  toast.error(`Failed to delete agenda: ${err.message}`),
                              })
                            }
                          }}
                        >
                          Clear
                        </Button>
                      )}
                      <Button
                        variant={meeting.agenda ? 'outline' : 'default'}
                        size="sm"
                        className="h-8 gap-1.5 text-xs"
                        onClick={() => setAgendaOpen(true)}
                      >
                        <SparklesIcon className="size-3.5" />
                        {meeting.agenda ? 'Edit agenda' : 'Paste an agenda'}
                      </Button>
                    </div>
                  </div>

                  {meeting.agenda &&
                  ((meeting.agenda.items?.length ?? 0) > 0 ||
                    (meeting.agenda.action_items?.length ?? 0) > 0) ? (
                    <div className="flex flex-col gap-4 rounded-lg border border-border bg-card/60 p-3.5">
                      {meeting.ai_suggestion && (
                        <div className="flex items-center justify-between border-b border-border/60 pb-2 text-xs text-muted-foreground">
                          <span className="flex items-center gap-1.5">
                            <SparklesIcon className="size-3 text-primary" />
                            Parsed by {meeting.ai_suggestion.model}
                          </span>
                          <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
                            {meeting.ai_suggestion.prompt_version}
                          </Badge>
                        </div>
                      )}

                      {meeting.agenda.items && meeting.agenda.items.length > 0 && (
                        <div className="space-y-2">
                          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                            Topics
                          </h4>
                          <ol className="list-inside list-decimal space-y-1.5 text-sm">
                            {meeting.agenda.items.map((item, idx) => (
                              <li key={idx} className="leading-snug">
                                <span className="font-medium text-foreground">{item.topic}</span>
                                {item.minutes !== null && item.minutes !== undefined && (
                                  <Badge
                                    variant="secondary"
                                    className="ml-2 px-1.5 py-0 text-[10px]"
                                  >
                                    {item.minutes} min
                                  </Badge>
                                )}
                                {item.owner && (
                                  <Badge
                                    variant="outline"
                                    className="ml-1.5 px-1.5 py-0 text-[10px]"
                                  >
                                    @{item.owner}
                                  </Badge>
                                )}
                              </li>
                            ))}
                          </ol>
                        </div>
                      )}

                      {meeting.agenda.action_items && meeting.agenda.action_items.length > 0 && (
                        <div className="space-y-2">
                          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                            Action Items
                          </h4>
                          <ul className="space-y-2 text-sm">
                            {meeting.agenda.action_items.map((act, idx) => (
                              <li
                                key={idx}
                                className="flex items-start gap-2 rounded-md bg-muted/40 p-2 text-sm"
                              >
                                <CheckCircle2Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                                <div className="flex-1 space-y-1">
                                  <p className="leading-tight text-foreground">{act.task}</p>
                                  <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                                    {act.owner && (
                                      <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
                                        @{act.owner}
                                      </Badge>
                                    )}
                                    {act.due && (
                                      <span className="text-[11px] text-muted-foreground">
                                        Due: {act.due}
                                      </span>
                                    )}
                                  </div>
                                </div>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-lg border border-dashed border-border/80 bg-muted/20 p-3.5 text-sm">
                      <p className="text-xs text-muted-foreground">
                        No agenda yet. Paste an email, Slack note, or rough bullets to extract
                        topics and action items with Claude.
                      </p>
                      <Button
                        variant="default"
                        size="sm"
                        className="shrink-0 gap-1.5 font-medium"
                        onClick={() => setAgendaOpen(true)}
                      >
                        <SparklesIcon className="size-3.5" />
                        Paste an agenda
                      </Button>
                    </div>
                  )}
                </div>
              </div>

              <DialogFooter className="sm:justify-between">
                <Button variant="ghost" onClick={() => onDelete(meeting)}>
                  <Trash2Icon />
                  Delete
                </Button>
                <div className="flex items-center gap-2">
                  <Button variant="outline" onClick={() => setAgendaOpen(true)}>
                    <SparklesIcon />
                    {meeting.agenda ? 'Edit agenda' : 'Paste an agenda'}
                  </Button>
                  <Button ref={editButtonRef} onClick={() => onEdit(meeting)}>
                    <PencilIcon />
                    Edit
                  </Button>
                </div>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>

      <PasteAgendaDialog meeting={meeting} open={agendaOpen} onOpenChange={setAgendaOpen} />
    </>
  )
}
