import { format, getHours, isToday, setHours, startOfHour } from 'date-fns'
import { MapPinIcon, PencilIcon, PlusIcon, SparklesIcon, Trash2Icon } from 'lucide-react'
import { Fragment } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { Meeting, Participant } from '@/lib/api'
import { meetingsOnDay } from '@/lib/calendar'
import { formatTimeOnDay } from '@/lib/format'

const MAX_BADGES = 3

function ParticipantBadges({ participants }: { participants: Participant[] }) {
  if (participants.length === 0) {
    return <span className="text-sm text-muted-foreground">—</span>
  }
  const shown = participants.slice(0, MAX_BADGES)
  const hidden = participants.slice(MAX_BADGES)
  return (
    <div className="flex flex-wrap gap-1">
      {shown.map((p) => (
        <Badge key={p.id} variant="secondary" title={p.email}>
          {p.name}
        </Badge>
      ))}
      {hidden.length > 0 && (
        <Badge variant="outline" title={hidden.map((p) => p.name).join(', ')}>
          +{hidden.length}
        </Badge>
      )}
    </div>
  )
}

type Props = {
  days: Date[]
  meetings: Meeting[]
  onCreateAt: (start: Date) => void
  onOpen: (meeting: Meeting) => void
  onEdit: (meeting: Meeting) => void
  onDelete: (meeting: Meeting) => void
}

function RowActions({
  meeting,
  onOpen,
  onEdit,
  onDelete,
}: { meeting: Meeting } & Pick<Props, 'onOpen' | 'onEdit' | 'onDelete'>) {
  // stopPropagation: the row itself opens the details view.
  return (
    <div className="flex shrink-0 items-center gap-1.5">
      <Button
        variant={meeting.agenda ? 'outline' : 'secondary'}
        size="sm"
        className="h-8 gap-1.5 px-2.5 text-xs font-medium"
        aria-label="Paste an agenda"
        title={meeting.agenda ? 'View / Edit agenda' : 'Paste an agenda'}
        onClick={(event) => {
          event.stopPropagation()
          onOpen(meeting)
        }}
      >
        <SparklesIcon className="size-3.5 text-primary" />
        <span>{meeting.agenda ? 'Agenda' : 'Paste agenda'}</span>
      </Button>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label={`Edit ${meeting.title}`}
        title="Edit"
        onClick={(event) => {
          event.stopPropagation()
          onEdit(meeting)
        }}
      >
        <PencilIcon />
      </Button>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label={`Delete ${meeting.title}`}
        title="Delete"
        onClick={(event) => {
          event.stopPropagation()
          onDelete(meeting)
        }}
      >
        <Trash2Icon />
      </Button>
    </div>
  )
}

/** Keyboard-reachable title; clicks bubble up to the row, which opens the details. */
function MeetingTitle({ meeting }: { meeting: Meeting }) {
  return (
    <button
      type="button"
      className="rounded-sm text-left font-serif text-xl font-medium text-heading transition-colors outline-none group-hover:text-hover focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      {meeting.title}
    </button>
  )
}

function MeetingRow({
  meeting,
  day,
  onOpen,
  onEdit,
  onDelete,
}: { meeting: Meeting; day: Date } & Omit<Props, 'days' | 'meetings' | 'onCreateAt'>) {
  const actions = (
    <RowActions meeting={meeting} onOpen={onOpen} onEdit={onEdit} onDelete={onDelete} />
  )
  return (
    <div
      className="group flex cursor-pointer flex-col gap-2 px-4 py-2.5 transition-colors hover:bg-muted md:grid md:grid-cols-[8rem_minmax(0,1fr)_minmax(0,12rem)_minmax(0,14rem)_auto] md:items-center md:gap-4"
      onClick={() => onOpen(meeting)}
    >
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold tabular-nums">{formatTimeOnDay(meeting, day)}</span>
        <div className="md:hidden">{actions}</div>
      </div>
      <div className="flex min-w-0 flex-col items-start">
        <MeetingTitle meeting={meeting} />
        {meeting.description && (
          <p className="w-full truncate text-sm text-muted-foreground" title={meeting.description}>
            {meeting.description}
          </p>
        )}
      </div>
      <div className="flex min-w-0 items-center gap-1 text-sm" title={meeting.place}>
        <MapPinIcon className="size-3.5 shrink-0 text-muted-foreground" />
        <span className="truncate">{meeting.place}</span>
      </div>
      <ParticipantBadges participants={meeting.participants} />
      <div className="hidden md:block">{actions}</div>
    </div>
  )
}

/** Default start for a meeting added from a day heading: 10:00, or the next full hour today. */
function defaultStart(day: Date): Date {
  const start = setHours(day, 10)
  if (!isToday(day)) return start
  const nextHour = startOfHour(new Date(Date.now() + 60 * 60 * 1000))
  return getHours(nextHour) > 10 && isToday(nextHour) ? nextHour : start
}

/** Agenda: every visible day gets a heading, followed by its meetings. */
export function MeetingList({ days, meetings, onCreateAt, ...handlers }: Props) {
  return (
    <div className="flex flex-col gap-4 pb-2">
      {days.map((day) => {
        const dayMeetings = meetingsOnDay(meetings, day)
        return (
          <section key={day.toISOString()} className="flex flex-col gap-1.5">
            <div className="flex items-baseline gap-3 px-1">
              <h2 className="text-xl">{format(day, 'EEEE')}</h2>
              <span className="font-serif text-muted-foreground italic">
                {format(day, 'd MMMM')}
              </span>
              {isToday(day) && <Badge>Today</Badge>}
              <Button
                variant="ghost"
                size="xs"
                className="ml-auto self-center"
                aria-label={`Add meeting on ${format(day, 'EEEE, d MMMM')}`}
                onClick={() => onCreateAt(defaultStart(day))}
              >
                <PlusIcon />
                Add
              </Button>
            </div>
            <div className="rounded-[20px] bg-card py-1">
              {dayMeetings.length === 0 ? (
                <p className="px-4 py-2 font-serif text-muted-foreground italic">No meetings</p>
              ) : (
                dayMeetings.map((meeting, i) => (
                  <Fragment key={meeting.id}>
                    {i > 0 && <div className="hairline mx-4" />}
                    <MeetingRow meeting={meeting} day={day} {...handlers} />
                  </Fragment>
                ))
              )}
            </div>
          </section>
        )
      })}
    </div>
  )
}
