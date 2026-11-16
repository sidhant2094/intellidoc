import { ArrowUp, CornerDownRight, FileSearch, Info, MessageSquareText, X } from 'lucide-react'
import type { PDFDocumentProxy } from 'pdfjs-dist'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { AnalysisFailure, ask } from '../lib/api'
import { cx } from '../lib/cx'
import { pageRange } from '../lib/format'
import type { Citation } from '../lib/types'
import { PageViewer } from './PageViewer'
import { IconButton, Spinner } from './ui'

export type ChatMessage =
  | { role: 'user'; text: string }
  | { role: 'assistant'; answer: string; supported: boolean; citations: Citation[] }
  | { role: 'error'; text: string }

const SUGGESTIONS = [
  'What are the three most important findings?',
  'What are the limitations or caveats?',
  'What should I read next?',
  'Explain the top result like I’m a beginner',
]

export function AskPanel({
  open,
  onClose,
  sessionId,
  messages,
  setMessages,
  pdf,
  fileUrl,
  onOpenResult,
}: {
  open: boolean
  onClose: () => void
  sessionId: string | null
  messages: ChatMessage[]
  setMessages: (fn: (m: ChatMessage[]) => ChatMessage[]) => void
  pdf: PDFDocumentProxy | null
  fileUrl: string | null
  onOpenResult: (resultId: string, page: number) => void
}) {
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState(false)
  const input = useRef<HTMLTextAreaElement>(null)
  const list = useRef<HTMLDivElement>(null)
  const abort = useRef<AbortController | null>(null)

  useEffect(() => {
    if (open) window.setTimeout(() => input.current?.focus(), 60)
  }, [open])

  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight, behavior: 'smooth' })
  }, [messages.length, pending])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  useEffect(() => () => abort.current?.abort(), [])

  const send = async (raw: string) => {
    const q = raw.trim()
    if (!q || pending || !sessionId) return
    setDraft('')
    setMessages((m) => [...m, { role: 'user', text: q }])
    setPending(true)
    const ctrl = new AbortController()
    abort.current = ctrl
    try {
      const res = await ask(sessionId, q, ctrl.signal)
      setMessages((m) => [...m, { role: 'assistant', ...res }])
    } catch (e) {
      if ((e as Error).name === 'AbortError') return
      const err = e instanceof AnalysisFailure ? e.error : null
      setMessages((m) => [
        ...m,
        {
          role: 'error',
          text:
            err?.code === 'session_expired'
              ? 'This analysis is no longer active. Run it again to keep asking questions.'
              : err?.code === 'backend_offline'
                ? 'Can’t reach IntelliDoc right now. It may be starting up — please try again in a moment.'
                : 'That question couldn’t be answered. Please try again.',
        },
      ])
    } finally {
      setPending(false)
    }
  }

  // Portal: animated ancestors would otherwise become the containing block for `position: fixed`.
  return createPortal(
    <>
      {open && (
        <div aria-hidden className="fixed inset-0 z-40 bg-black/20 animate-fade-in lg:hidden" onClick={onClose} />
      )}
      <aside
        aria-label="Ask IntelliDoc"
        aria-hidden={!open}
        inert={!open}
        className={cx(
          'fixed inset-y-0 right-0 z-50 flex w-full flex-col border-l border-line bg-surface shadow-lift transition-transform duration-300 ease-[cubic-bezier(0.2,0.7,0.2,1)] sm:w-[460px]',
          open ? 'translate-x-0' : 'translate-x-full',
        )}
      >
        <header className="flex items-center justify-between gap-3 border-b border-line px-5 py-4">
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent-soft text-accent-ink">
              <MessageSquareText size={18} strokeWidth={1.8} />
            </span>
            <div>
              <h2 className="text-[15px] font-semibold text-ink">Ask IntelliDoc</h2>
              <p className="text-[12.5px] text-ink-3">Answers come from this document, with citations.</p>
            </div>
          </div>
          <IconButton label="Close" onClick={onClose}>
            <X size={18} />
          </IconButton>
        </header>

        <div ref={list} className="flex-1 space-y-5 overflow-y-auto px-5 py-5 scroll-thin" aria-live="polite">
          {messages.length === 0 && (
            <div className="animate-fade-in">
              <p className="text-[14px] leading-relaxed text-ink-2">
                Ask anything about this PDF — compare sections, explain a passage at your level, or find evidence for a
                claim. Your role and objective are kept in mind.
              </p>
              <div className="mt-4 flex flex-col items-start gap-2">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => send(s)}
                    disabled={!sessionId}
                    className="inline-flex items-center gap-2 rounded-xl border border-line-strong bg-surface px-3 py-2 text-left text-[13.5px] text-ink-2 transition-colors hover:border-accent hover:text-ink disabled:opacity-50"
                  >
                    <CornerDownRight size={13} className="shrink-0 text-ink-3" />
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) =>
            m.role === 'user' ? (
              <div key={i} className="flex justify-end animate-fade-in">
                <p className="max-w-[85%] rounded-2xl rounded-br-md bg-accent px-4 py-2.5 text-[14.5px] leading-relaxed text-on-accent">
                  {m.text}
                </p>
              </div>
            ) : m.role === 'error' ? (
              <p key={i} className="rounded-xl bg-danger-soft px-4 py-3 text-[13.5px] text-danger animate-fade-in" role="alert">
                {m.text}
              </p>
            ) : (
              <Answer key={i} m={m} pdf={pdf} fileUrl={fileUrl} onOpenResult={onOpenResult} />
            ),
          )}

          {pending && (
            <div className="flex items-center gap-2.5 text-[13.5px] text-ink-3 animate-fade-in">
              <Spinner className="h-4 w-4 text-accent" /> Reading the relevant passages…
            </div>
          )}
        </div>

        <form
          className="border-t border-line p-4"
          onSubmit={(e) => {
            e.preventDefault()
            send(draft)
          }}
        >
          <div className="flex items-end gap-2 rounded-2xl border border-line-strong bg-surface-2 p-2 transition-colors focus-within:border-accent focus-within:bg-surface focus-within:ring-4 focus-within:ring-accent-soft">
            <textarea
              ref={input}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  send(draft)
                }
              }}
              rows={Math.min(4, Math.max(1, draft.split('\n').length))}
              maxLength={500}
              placeholder={sessionId ? 'Ask about this document…' : 'Run an analysis to ask questions'}
              disabled={!sessionId}
              aria-label="Your question"
              className="max-h-32 flex-1 resize-none bg-transparent px-2 py-1.5 text-[14.5px] leading-relaxed text-ink outline-none placeholder:text-ink-3"
            />
            <button
              type="submit"
              aria-label="Send question"
              disabled={!draft.trim() || pending || !sessionId}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent text-on-accent transition-opacity disabled:opacity-35"
            >
              <ArrowUp size={17} strokeWidth={2.2} />
            </button>
          </div>
        </form>
      </aside>
    </>,
    document.body,
  )
}

function Answer({
  m,
  pdf,
  fileUrl,
  onOpenResult,
}: {
  m: Extract<ChatMessage, { role: 'assistant' }>
  pdf: PDFDocumentProxy | null
  fileUrl: string | null
  onOpenResult: (resultId: string, page: number) => void
}) {
  const [active, setActive] = useState<number | null>(null)
  const parts: ReactNode[] = []
  m.answer.split(/(\[\d+\])/).forEach((chunk, i) => {
    const hit = chunk.match(/^\[(\d+)\]$/)
    if (hit && m.citations.some((c) => c.n === Number(hit[1]))) {
      const n = Number(hit[1])
      parts.push(
        <button
          key={i}
          onClick={() => setActive(active === n ? null : n)}
          aria-label={`Show citation ${n}`}
          className={cx(
            'mx-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-px items-center justify-center rounded-md px-1 align-middle text-[11px] font-semibold tabular-nums transition-colors',
            active === n ? 'bg-accent text-on-accent' : 'bg-accent-soft-2 text-accent-ink hover:bg-accent hover:text-on-accent',
          )}
        >
          {n}
        </button>,
      )
    } else if (!hit) {
      parts.push(chunk)
    }
  })

  return (
    <div className="animate-fade-in">
      {!m.supported && (
        <p className="mb-2 flex items-center gap-1.5 text-[12px] font-medium text-ink-3">
          <Info size={13} /> Not clearly answered by this document
        </p>
      )}
      <p className="text-[15px] leading-relaxed text-ink">{parts}</p>
      {m.citations.length > 0 && (
        <ol className="mt-3 space-y-2">
          {m.citations.map((c) => (
            <CitationCard
              key={c.n}
              c={c}
              open={active === c.n}
              onToggle={() => setActive(active === c.n ? null : c.n)}
              pdf={pdf}
              fileUrl={fileUrl}
              onOpenResult={onOpenResult}
            />
          ))}
        </ol>
      )}
    </div>
  )
}

function CitationCard({
  c,
  open,
  onToggle,
  pdf,
  fileUrl,
  onOpenResult,
}: {
  c: Citation
  open: boolean
  onToggle: () => void
  pdf: PDFDocumentProxy | null
  fileUrl: string | null
  onOpenResult: (resultId: string, page: number) => void
}) {
  const [page, setPage] = useState(c.excerpt_page)
  return (
    <li className={cx('rounded-xl border transition-colors', open ? 'border-accent/40 bg-surface-2' : 'border-line bg-surface')}>
      <button onClick={onToggle} aria-expanded={open} className="flex w-full items-start gap-3 px-3 py-2.5 text-left">
        <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-accent-soft-2 text-[11px] font-semibold text-accent-ink">
          {c.n}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13.5px] font-medium text-ink">{c.title}</span>
          <span className="text-[12px] text-ink-3">{pageRange(c.page_start, c.page_end, true)}</span>
        </span>
      </button>
      {open && (
        <div className="px-3 pb-3 animate-fade-in">
          <blockquote className="border-l-2 border-accent pl-3 text-[13.5px] leading-relaxed text-ink-2">
            “{c.excerpt}” <span className="whitespace-nowrap text-[12px] text-ink-3">— p. {c.excerpt_page}</span>
          </blockquote>
          <div className="mt-3 flex flex-wrap gap-2">
            {c.result_id && (
              <button
                onClick={() => onOpenResult(c.result_id!, c.excerpt_page)}
                className="inline-flex items-center gap-1.5 rounded-lg bg-accent-soft px-2.5 py-1 text-[12.5px] font-medium text-accent-ink hover:bg-accent-soft-2"
              >
                <CornerDownRight size={13} /> Open in reading path
              </button>
            )}
          </div>
          {pdf && (
            <div className="mt-3">
              <p className="mb-2 flex items-center gap-1.5 text-[12px] font-medium text-ink-3">
                <FileSearch size={13} /> Cited page
              </p>
              <PageViewer pdf={pdf} page={page} onPage={setPage} highlights={[]} fileUrl={fileUrl} />
            </div>
          )}
        </div>
      )}
    </li>
  )
}
