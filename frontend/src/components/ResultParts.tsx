import { AlignLeft, ChevronDown, Code2, Image, Table2 } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { scorePct } from '../lib/format'
import type { AnalysisInfo, ContentType, Result, SignalName } from '../lib/types'
import { cx } from '../lib/cx'

const TYPE_META: Record<ContentType, { label: string; icon: ReactNode }> = {
  prose: { label: 'Prose', icon: <AlignLeft size={12.5} /> },
  table: { label: 'Table', icon: <Table2 size={12.5} /> },
  code: { label: 'Code', icon: <Code2 size={12.5} /> },
  figure: { label: 'Figure', icon: <Image size={12.5} /> },
}

export function TypeTag({ type }: { type: ContentType }) {
  const m = TYPE_META[type]
  return (
    <span className="inline-flex h-6 items-center gap-1 rounded-md border border-line bg-surface-2 px-2 text-[12px] font-medium text-ink-2">
      {m.icon}
      {m.label}
    </span>
  )
}

export function ScorePill({ score, label }: { score: number; label: string }) {
  const tone = score >= 0.62 ? 'strong' : score >= 0.45 ? 'mid' : 'weak'
  return (
    <span
      className={cx(
        'inline-flex h-6 items-center gap-1.5 rounded-md px-2 text-[12px] font-semibold',
        tone === 'strong' && 'bg-accent text-on-accent',
        tone === 'mid' && 'bg-accent-soft-2 text-accent-ink',
        tone === 'weak' && 'bg-surface-3 text-ink-2',
      )}
      title="Relative match score within this document — not a probability"
    >
      {label}
      <span className="font-medium tabular-nums opacity-80">{scorePct(score)}</span>
    </span>
  )
}

export function ScoreBar({ score, className }: { score: number; className?: string }) {
  return (
    <span className={cx('block h-1 overflow-hidden rounded-full bg-surface-3', className)} aria-hidden>
      <span className="block h-full rounded-full bg-accent" style={{ width: `${Math.max(4, scorePct(score))}%` }} />
    </span>
  )
}

export function Disclosure({
  title,
  aside,
  children,
  defaultOpen = false,
}: {
  title: string
  aside?: ReactNode
  children: ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border-t border-line">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-3 rounded-lg py-4 text-left"
      >
        <span className="text-[14px] font-semibold text-ink">{title}</span>
        <span className="flex items-center gap-3 text-[12.5px] text-ink-3">
          {aside}
          <ChevronDown size={17} className={cx('transition-transform duration-200', open && 'rotate-180')} />
        </span>
      </button>
      {open && <div className="pb-5 animate-fade-in">{children}</div>}
    </div>
  )
}

/** Full section text with page dividers and the excerpt marked. */
export function ContextView({ r, onPage }: { r: Result; onPage: (p: number) => void }) {
  const marks = r.context_pages
  const { start, end } = r.context_excerpt
  const blocks: ReactNode[] = []
  marks.forEach((m, i) => {
    const segEnd = i + 1 < marks.length ? marks[i + 1].offset : r.context.length
    const segStart = m.offset
    if (i > 0 || marks.length > 1) {
      blocks.push(
        <div key={`p${i}`} className="my-4 flex items-center gap-3 first:mt-0">
          <button
            onClick={() => onPage(m.page)}
            className="rounded-md bg-surface-3 px-2 py-0.5 text-[11.5px] font-semibold uppercase tracking-wide text-ink-3 hover:text-accent-ink"
          >
            Page {m.page}
          </button>
          <span className="h-px flex-1 bg-line" />
        </div>,
      )
    }
    const parts: ReactNode[] = []
    const a = Math.max(segStart, Math.min(start, segEnd))
    const b = Math.max(segStart, Math.min(end, segEnd))
    parts.push(r.context.slice(segStart, a))
    if (b > a) parts.push(<mark key="m">{r.context.slice(a, b)}</mark>)
    parts.push(r.context.slice(b, segEnd))
    blocks.push(
      <div key={`t${i}`} className="whitespace-pre-line">
        {parts}
      </div>,
    )
  })
  return (
    <div className="max-h-[480px] overflow-y-auto rounded-xl bg-surface-2 p-4 text-[14px] leading-[1.7] text-ink-2 scroll-thin sm:p-5">
      {blocks}
    </div>
  )
}

const SIGNAL_META: Record<SignalName, { label: string; note: string }> = {
  semantic: { label: 'Meaning similarity', note: 'How closely the passage’s meaning matches your objective' },
  keyword: { label: 'Keyword coverage', note: 'Share of your key terms present' },
  contextual: { label: 'Contextual relevance', note: 'Usefulness for your objective, judged from the content' },
  content_type: { label: 'Content type', note: 'Requested tables / code / figures present' },
  expertise: { label: 'Expertise fit', note: 'Complexity vs. your level, role vocabulary' },
  structure: { label: 'Structure', note: 'Heading depth and heading match' },
}

export function ScoreBreakdown({ r, analysis }: { r: Result; analysis: AnalysisInfo }) {
  const order: SignalName[] = ['semantic', 'keyword', 'contextual', 'content_type', 'expertise', 'structure']
  const active = order.filter((k) => (analysis.weights[k] ?? 0) > 0)
  return (
    <div>
      <ul className="space-y-3.5">
        {active.map((k) => (
          <li key={k} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1.5">
            <div className="min-w-0">
              <span className="text-[13.5px] font-medium text-ink">{SIGNAL_META[k].label}</span>
              <span className="ml-2 text-[12px] text-ink-3">{SIGNAL_META[k].note}</span>
            </div>
            <span className="text-[12px] tabular-nums text-ink-3">{Math.round(analysis.weights[k] * 100)}% weight</span>
            <ScoreBar score={r.signals[k] ?? 0} className="col-span-2 h-1.5" />
          </li>
        ))}
      </ul>
      <p className="mt-4 text-[12px] leading-relaxed text-ink-3">
        Each signal is normalized to 0–1 and combined. Content type, expertise and structure can re-order relevant
        passages but can’t lift an off-topic one. The match score ranks sections within this document; it isn’t a
        probability or a measure of factual confidence.
      </p>
    </div>
  )
}
