import { Check, FileText } from 'lucide-react'
import type { StageName } from '../lib/types'
import { Button, Card, Spinner } from './ui'
import { cx } from '../lib/cx'

const STAGES: { key: StageName; label: string }[] = [
  { key: 'reading', label: 'Reading your document' },
  { key: 'sections', label: 'Reconstructing sections' },
  { key: 'matching', label: 'Matching your objective' },
  { key: 'ranking', label: 'Ranking relevant sections' },
]

export function Analyzing({
  filename,
  current,
  details,
  done,
  onCancel,
}: {
  filename: string
  current: StageName | null
  details: Partial<Record<StageName, string>>
  done: boolean
  onCancel: () => void
}) {
  const currentIdx = current ? STAGES.findIndex((s) => s.key === current) : -1
  return (
    <div className="mx-auto flex max-w-[520px] flex-col px-4 pb-24 pt-16 sm:pt-24 animate-fade-up">
      <Card className="p-6 sm:p-8">
        <div className="mb-7 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-soft text-accent-ink">
            <FileText size={19} strokeWidth={1.8} />
          </div>
          <div className="min-w-0">
            <p className="text-[13px] text-ink-3">Analyzing</p>
            <p className="truncate text-[15px] font-semibold text-ink">{filename}</p>
          </div>
        </div>
        <ol className="relative space-y-1" aria-live="polite">
          {STAGES.map((s, i) => {
            const state = done || i < currentIdx ? 'done' : i === currentIdx ? 'active' : 'pending'
            return (
              <li key={s.key} className="relative flex gap-3.5 py-2.5">
                {i < STAGES.length - 1 && (
                  <span
                    aria-hidden
                    className={cx(
                      'absolute left-[11px] top-[34px] h-[calc(100%-22px)] w-px transition-colors duration-300',
                      state === 'done' ? 'bg-accent' : 'bg-line-strong',
                    )}
                  />
                )}
                <span
                  className={cx(
                    'relative z-10 flex h-6 w-6 shrink-0 items-center justify-center rounded-full transition-colors duration-300',
                    state === 'done' && 'bg-accent text-on-accent',
                    state === 'active' && 'bg-accent-soft text-accent',
                    state === 'pending' && 'border border-line-strong bg-surface text-ink-3',
                  )}
                >
                  {state === 'done' ? <Check size={13} strokeWidth={3} /> : state === 'active' ? <Spinner className="h-3.5 w-3.5" /> : null}
                </span>
                <div className="min-w-0 pt-0.5">
                  <p className={cx('text-[15px] font-medium transition-colors', state === 'pending' ? 'text-ink-3' : 'text-ink')}>
                    {s.label}
                    <span className="sr-only">{state === 'done' ? ' — done' : state === 'active' ? ' — in progress' : ''}</span>
                  </p>
                  {details[s.key] && state !== 'pending' && (
                    <p className="mt-0.5 text-[13px] text-ink-3 animate-fade-in">{details[s.key]}</p>
                  )}
                </div>
              </li>
            )
          })}
        </ol>
        <div className="mt-6 flex justify-end">
          <Button variant="ghost" size="sm" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </Card>
      <p className="mt-4 text-center text-[12.5px] text-ink-3">Each step updates as it completes.</p>
    </div>
  )
}
