import { AlertTriangle, ArrowLeft, Download, FileText, Layers, Lightbulb, MessageSquareText, Pencil, Plus, SearchX } from 'lucide-react'
import type { PDFDocumentProxy } from 'pdfjs-dist'
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { download, formatDuration, pageRange, toMarkdown } from '../lib/format'
import type { AnalyzeResponse, Insight, Result } from '../lib/types'
import { AskPanel, type ChatMessage } from './AskPanel'
import { ResultDetail } from './ResultDetail'
import { ScoreBar } from './ResultParts'
import { Button, Card } from './ui'
import { cx } from '../lib/cx'

export function Results({
  data,
  pdf,
  fileUrl,
  onEdit,
  onNew,
}: {
  data: AnalyzeResponse
  pdf: PDFDocumentProxy | null
  fileUrl: string | null
  onEdit: () => void
  onNew: () => void
}) {
  const { results, analysis, document: doc } = data
  const [selected, setSelected] = useState(0)
  const [chatOpen, setChatOpen] = useState(false)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [pageRequest, setPageRequest] = useState<{ id: string; page: number; nonce: number } | null>(null)
  const detailRef = useRef<HTMLDivElement>(null)
  const railRefs = useRef<(HTMLButtonElement | null)[]>([])

  const select = (i: number, scroll = false) => {
    const next = Math.max(0, Math.min(results.length - 1, i))
    setSelected(next)
    railRefs.current[next]?.scrollIntoView({ block: 'nearest' })
    if (scroll && window.innerWidth < 1024) detailRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (t.closest('input, textarea, dialog[open], aside[aria-label="Ask IntelliDoc"]') || e.metaKey || e.ctrlKey || e.altKey) return
      if (e.key === 'j' || e.key === 'ArrowDown') {
        e.preventDefault()
        setSelected((s) => Math.min(results.length - 1, s + 1))
      } else if (e.key === 'k' || e.key === 'ArrowUp') {
        e.preventDefault()
        setSelected((s) => Math.max(0, s - 1))
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [results.length])

  useEffect(() => {
    railRefs.current[selected]?.scrollIntoView({ block: 'nearest' })
  }, [selected])

  const openResult = (resultId: string, page?: number) => {
    const i = results.findIndex((r) => r.id === resultId)
    if (i < 0) return
    if (page) setPageRequest({ id: resultId, page, nonce: Date.now() })
    select(i, true)
    if (window.innerWidth < 1024) setChatOpen(false)
  }

  const exportMd = () =>
    download(`${doc.filename.replace(/\.pdf$/i, '')} — reading path.md`, toMarkdown(data))

  return (
    <div className="mx-auto max-w-[1440px] px-4 pb-28 pt-6 sm:px-6 lg:px-8 animate-fade-up">
      {/* Header */}
      <div className="flex flex-col gap-5 border-b border-line pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <button
            onClick={onEdit}
            className="mb-3 inline-flex items-center gap-1.5 rounded-lg text-[13px] font-medium text-ink-3 hover:text-ink"
          >
            <ArrowLeft size={14} /> Back to setup
          </button>
          <div className="flex items-center gap-2 text-[13px] text-ink-3">
            <FileText size={14} />
            <span className="truncate">{doc.filename}</span>
          </div>
          <h1 className="mt-1.5 max-w-[880px] font-display text-[24px] font-semibold leading-snug tracking-[-0.025em] text-ink sm:text-[28px]">
            “{analysis.objective}”
          </h1>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-[13px]">
            <span className="rounded-full bg-accent-soft px-2.5 py-0.5 font-medium text-accent-ink">{analysis.persona}</span>
            <span className="rounded-full bg-surface-3 px-2.5 py-0.5 font-medium text-ink-2">{analysis.expertise}</span>
            {analysis.focus_terms.map((t) => (
              <span key={t} className="rounded-full border border-line-strong px-2.5 py-0.5 text-ink-2">
                {t}
              </span>
            ))}
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <Button size="sm" variant="ghost" onClick={onEdit}>
            <Pencil size={14} /> Refine objective
          </Button>
          {data.session_id && (
            <Button size="sm" onClick={() => setChatOpen(true)}>
              <MessageSquareText size={14} /> Ask IntelliDoc
            </Button>
          )}
          {results.length > 0 && (
            <Button size="sm" onClick={exportMd}>
              <Download size={14} /> Export
            </Button>
          )}
          <Button size="sm" variant="primary" onClick={onNew}>
            <Plus size={15} /> New analysis
          </Button>
        </div>
      </div>

      {results.length === 0 ? (
        <div className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
          <EmptyState onEdit={onEdit} insights={data.insights} />
          <aside className="space-y-5">
            <DocDetails data={data} />
          </aside>
        </div>
      ) : (
        <div className="mt-6 grid gap-6 lg:grid-cols-[300px_minmax(0,1fr)] xl:grid-cols-[300px_minmax(0,1fr)_300px]">
          {/* Rail */}
          <nav aria-label="Ranked results" className="lg:sticky lg:top-20 lg:max-h-[calc(100vh-6rem)] lg:self-start">
            <div className="mb-3 flex items-baseline justify-between px-1">
              <h2 className="text-[13px] font-semibold text-ink">Your reading path</h2>
              <span className="text-[12px] text-ink-3">
                {results.length} section{results.length === 1 ? '' : 's'}
              </span>
            </div>
            <ol className="space-y-1 overflow-y-auto pr-1 scroll-thin lg:max-h-[calc(100vh-9rem)]">
              {results.map((r, i) => (
                <li key={r.id}>
                  <button
                    ref={(el) => {
                      railRefs.current[i] = el
                    }}
                    onClick={() => select(i, true)}
                    aria-current={i === selected ? 'true' : undefined}
                    className={cx(
                      'group relative flex w-full gap-3 rounded-[14px] px-3 py-3 text-left transition-colors',
                      i === selected ? 'bg-surface shadow-card' : 'hover:bg-surface-3/70',
                    )}
                  >
                    {i === selected && <span aria-hidden className="absolute bottom-3 left-0 top-3 w-[3px] rounded-full bg-accent" />}
                    <span
                      className={cx(
                        'w-5 shrink-0 pt-px text-[13px] font-semibold tabular-nums',
                        i === selected ? 'text-accent-ink' : 'text-ink-3',
                      )}
                    >
                      {r.rank}
                    </span>
                    <span className="min-w-0 flex-1">
                      {r.breadcrumb.length > 1 && (
                        <span className="block truncate text-[11.5px] text-ink-3">{r.breadcrumb.slice(0, -1).join(' › ')}</span>
                      )}
                      <span className={cx('line-clamp-2 text-[14px] font-medium leading-snug', i === selected ? 'text-ink' : 'text-ink-2 group-hover:text-ink')}>
                        {r.title}
                      </span>
                      <span className="mt-2 flex items-center gap-2.5">
                        <span className="text-[12px] tabular-nums text-ink-3">{pageRange(r.page_start, r.page_end)}</span>
                        <ScoreBar score={r.match_score} className="flex-1" />
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ol>
            <p className="mt-3 hidden px-1 text-[11.5px] text-ink-3 lg:block">
              Tip: use <kbd className="rounded border border-line-strong px-1 font-sans">↑</kbd>{' '}
              <kbd className="rounded border border-line-strong px-1 font-sans">↓</kbd> to move between results.
            </p>
          </nav>

          {/* Detail */}
          <div ref={detailRef} className="min-w-0 scroll-mt-20">
            <ResultDetail
              key={`${results[selected].id}-${pageRequest?.id === results[selected].id ? pageRequest.nonce : 0}`}
              initialPage={pageRequest?.id === results[selected].id ? pageRequest.page : undefined}
              r={results[selected]}
              total={results.length}
              analysis={analysis}
              pdf={pdf}
              fileUrl={fileUrl}
              onPrev={() => select(selected - 1)}
              onNext={() => select(selected + 1)}
            />
          </div>

          {/* Right rail */}
          <aside className="space-y-5 lg:col-span-2 xl:col-span-1 xl:sticky xl:top-20 xl:self-start">
            {data.insights.length > 0 && <Insights insights={data.insights} results={results} onOpen={openResult} />}
            <DocDetails data={data} />
          </aside>
        </div>
      )}

      {data.session_id &&
        !chatOpen &&
        createPortal(
        <button
          onClick={() => setChatOpen(true)}
          className="fixed bottom-5 right-5 z-30 inline-flex h-12 items-center gap-2 rounded-full bg-accent px-5 text-[14.5px] font-medium text-on-accent shadow-lift transition-transform hover:bg-accent-hover active:scale-[0.98] animate-fade-up sm:bottom-7 sm:right-7"
        >
          <MessageSquareText size={18} /> Ask IntelliDoc
        </button>,
          document.body,
        )}
      <AskPanel
        open={chatOpen}
        onClose={() => setChatOpen(false)}
        sessionId={data.session_id}
        messages={messages}
        setMessages={setMessages}
        pdf={pdf}
        fileUrl={fileUrl}
        onOpenResult={openResult}
      />
    </div>
  )
}

const KIND_LABEL: Record<Insight['kind'], string> = {
  concentration: 'Where the answers cluster',
  recurring: 'A recurring concept',
  gap: 'Not covered',
  theme: 'Theme',
  relationship: 'Connection',
  contradiction: 'Tension',
  repetition: 'Repeated finding',
  risk: 'Risk',
}

function Insights({
  insights,
  results,
  onOpen,
}: {
  insights: Insight[]
  results: Result[]
  onOpen: (id: string) => void
}) {
  const byId = new Map(results.map((r) => [r.id, r]))
  return (
    <Card className="p-5">
      <h2 className="mb-4 flex items-center gap-2 text-[13px] font-semibold text-ink">
        <Lightbulb size={15} className="text-accent" /> Top insights
      </h2>
      <ul className="space-y-5">
        {insights.map((ins, i) => (
          <li key={i}>
            <p className="text-[11.5px] font-semibold uppercase tracking-[0.05em] text-ink-3">{KIND_LABEL[ins.kind]}</p>
            {ins.kind !== 'concentration' && ins.kind !== 'recurring' && ins.title !== 'Not found in this document' && (
              <p className="mt-1 text-[13.5px] font-semibold leading-snug text-ink">{ins.title}</p>
            )}
            <p className="mt-1 text-[13.5px] leading-relaxed text-ink-2">{ins.text}</p>
            {ins.result_ids.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {ins.result_ids.map((id) => {
                  const r = byId.get(id)
                  if (!r) return null
                  return (
                    <button
                      key={id}
                      onClick={() => onOpen(id)}
                      title={r.title}
                      className="inline-flex h-6 items-center gap-1 rounded-md border border-line-strong px-1.5 text-[11.5px] font-medium tabular-nums text-ink-2 hover:border-accent hover:text-accent-ink"
                    >
                      #{r.rank}
                      <span className="text-ink-3">· {pageRange(r.page_start, r.page_end)}</span>
                    </button>
                  )
                })}
              </div>
            )}
          </li>
        ))}
      </ul>
      <p className="mt-4 text-[11.5px] text-ink-3">Drawn only from the sections in your reading path.</p>
    </Card>
  )
}

const SOURCE_LABEL = {
  outline: 'PDF bookmarks',
  headings: 'Layout (approximate)',
  pages: 'By page',
} as const

function DocDetails({ data }: { data: AnalyzeResponse }) {
  const { document: d, analysis: a, warnings } = data
  const rows: [string, string][] = [
    ['Pages with text', `${d.pages_with_text} of ${d.page_count}`],
    ['Sections found', String(d.section_count)],
    ['Passages scored', String(d.chunk_count)],
    ['Structure from', SOURCE_LABEL[d.structure_source]],
    ['Time taken', formatDuration(a.duration_ms)],
  ]
  return (
    <Card className="p-5">
      <h2 className="mb-4 flex items-center gap-2 text-[13px] font-semibold text-ink">
        <Layers size={15} className="text-ink-3" /> Analysis details
      </h2>
      <dl className="space-y-2.5">
        {rows.map(([k, v]) => (
          <div key={k} className="flex items-baseline justify-between gap-4 text-[13px]">
            <dt className="text-ink-3">{k}</dt>
            <dd className="text-right font-medium tabular-nums text-ink">{v}</dd>
          </div>
        ))}
      </dl>
      {warnings.length > 0 && (
        <ul className="mt-4 space-y-2">
          {warnings.map((w) => (
            <li key={w.code} className="flex gap-2 rounded-xl bg-warning-soft p-3 text-[12.5px] leading-relaxed text-ink-2">
              <AlertTriangle size={14} className="mt-0.5 shrink-0 text-warning" />
              {w.message}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-4 border-t border-line pt-4 text-[11.5px] leading-relaxed text-ink-3">
        Match scores rank sections within this document by meaning, keywords, context, content type, expertise and
        structure. They aren’t probabilities.
      </p>
    </Card>
  )
}

function EmptyState({ onEdit, insights }: { onEdit: () => void; insights: Insight[] }) {
  const gap = insights.find((i) => i.kind === 'gap')
  return (
    <Card className="flex flex-col items-center px-6 py-14 text-center sm:px-12">
      <div className="mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-surface-3 text-ink-3">
        <SearchX size={24} strokeWidth={1.8} />
      </div>
      <h2 className="font-display text-[22px] font-semibold tracking-[-0.02em] text-ink">
        No sufficiently relevant sections found
      </h2>
      <p className="mt-2 max-w-[460px] text-[15px] leading-relaxed text-ink-2">
        Nothing in this PDF matched your objective strongly enough to recommend. Rather than pad the list, IntelliDoc
        shows nothing.
      </p>
      {gap && <p className="mt-4 max-w-[460px] rounded-xl bg-surface-2 px-4 py-3 text-[13.5px] text-ink-2">{gap.text}</p>}
      <ul className="mt-6 space-y-1.5 text-left text-[14px] text-ink-2">
        <li>• Use the vocabulary the document itself is likely to use.</li>
        <li>• Name a specific topic (“refund policy”) rather than a goal (“help me decide”).</li>
        <li>• Remove focus terms that may not appear in this document.</li>
      </ul>
      <Button variant="primary" className="mt-8" onClick={onEdit}>
        <Pencil size={15} /> Refine your objective
      </Button>
    </Card>
  )
}
