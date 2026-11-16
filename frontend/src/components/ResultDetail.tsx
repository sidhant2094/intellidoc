import { AlertTriangle, ArrowLeft, ArrowRight, ChevronRight, Crosshair, FileSearch, Lightbulb, ListChecks, Quote } from 'lucide-react'
import type { PDFDocumentProxy } from 'pdfjs-dist'
import { useEffect, useState, type ReactNode } from 'react'
import { pageRange } from '../lib/format'
import type { AnalysisInfo, Result } from '../lib/types'
import { PageViewer } from './PageViewer'
import { ContextView, Disclosure, ScoreBreakdown, ScorePill, TypeTag } from './ResultParts'
import { Button, Card } from './ui'

function Label({ icon, children }: { icon?: ReactNode; children: ReactNode }) {
  return (
    <h3 className="mb-2.5 flex items-center gap-2 text-[12px] font-semibold uppercase tracking-[0.06em] text-ink-3">
      {icon}
      {children}
    </h3>
  )
}

function Bullets({ items }: { items: string[] }) {
  return (
    <ul className="space-y-2">
      {items.map((t, i) => (
        <li key={i} className="flex gap-3 text-[15px] leading-relaxed text-ink-2">
          <span aria-hidden className="mt-[10px] h-1 w-1 shrink-0 rounded-full bg-accent" />
          <span>{t}</span>
        </li>
      ))}
    </ul>
  )
}

export function ResultDetail({
  r,
  total,
  analysis,
  pdf,
  fileUrl,
  initialPage,
  onPrev,
  onNext,
}: {
  r: Result
  total: number
  analysis: AnalysisInfo
  pdf: PDFDocumentProxy | null
  fileUrl: string | null
  initialPage?: number
  onPrev: () => void
  onNext: () => void
}) {
  // The parent keys this component per result (and per page request), so state resets.
  const [page, setPage] = useState(initialPage ?? r.excerpt_page)

  const showPage = (p: number) => {
    setPage(p)
    document.getElementById('source-page')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  useEffect(() => {
    if (initialPage) document.getElementById('source-page')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [initialPage])

  const crumbs = r.breadcrumb.slice(0, -1)
  const hasDetail = r.findings.length > 0 || r.takeaways.length > 0

  return (
    <Card className="overflow-hidden animate-fade-in">
      <article className="p-5 sm:p-8" aria-labelledby={`title-${r.id}`}>
        <div className="flex items-center justify-between gap-4">
          <span className="font-display text-[13px] font-semibold tabular-nums tracking-wide text-ink-3">
            {String(r.rank).padStart(2, '0')} <span className="font-normal">/ {String(total).padStart(2, '0')}</span>
          </span>
          <div className="flex gap-1">
            <Button size="sm" variant="ghost" onClick={onPrev} disabled={r.rank === 1} aria-label="Previous result">
              <ArrowLeft size={15} />
            </Button>
            <Button size="sm" variant="ghost" onClick={onNext} disabled={r.rank === total} aria-label="Next result">
              <ArrowRight size={15} />
            </Button>
          </div>
        </div>

        {crumbs.length > 0 && (
          <nav aria-label="Section path" className="mt-4 flex flex-wrap items-center gap-1 text-[13px] text-ink-3">
            {crumbs.map((c, i) => (
              <span key={i} className="inline-flex items-center gap-1">
                {c}
                <ChevronRight size={13} />
              </span>
            ))}
          </nav>
        )}
        <h2
          id={`title-${r.id}`}
          className="mt-1.5 font-display text-[26px] font-semibold leading-tight tracking-[-0.025em] text-ink sm:text-[30px]"
        >
          {r.title}
        </h2>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button
            onClick={() => showPage(r.page_start)}
            className="inline-flex h-6 items-center gap-1.5 rounded-md border border-line-strong bg-surface px-2 text-[12px] font-semibold text-ink hover:border-accent hover:text-accent-ink"
          >
            {pageRange(r.page_start, r.page_end, true)}
          </button>
          <ScorePill score={r.match_score} label={r.relevance_label} />
          {r.content_types.map((t) => (
            <TypeTag key={t} type={t} />
          ))}
        </div>

        <section className="mt-8">
          <Label icon={<Crosshair size={14} />}>Why this matters</Label>
          <p className="text-[16px] leading-relaxed text-ink">{r.why_relevant}</p>
          {r.summary && <p className="mt-3 text-[15px] leading-relaxed text-ink-2">{r.summary}</p>}
        </section>

        <section className="mt-8">
          <Label icon={<Quote size={14} />}>From the source</Label>
          <figure className="relative rounded-2xl bg-accent-soft px-5 py-4 sm:px-6 sm:py-5">
            <span aria-hidden className="absolute bottom-4 left-0 top-4 w-[3px] rounded-full bg-accent" />
            <blockquote className="text-[16px] leading-[1.7] text-ink sm:text-[17px]">{r.excerpt}</blockquote>
            <figcaption className="mt-3 flex items-center gap-2 text-[13px] text-ink-2">
              Verbatim, page {r.excerpt_page}
              <span aria-hidden>·</span>
              <button onClick={() => showPage(r.excerpt_page)} className="font-medium text-accent-ink hover:underline">
                Show on page
              </button>
            </figcaption>
          </figure>
        </section>

        {hasDetail && (
          <div className="mt-8 grid gap-6 md:grid-cols-2">
            {r.findings.length > 0 && (
              <section>
                <Label icon={<ListChecks size={14} />}>Important findings</Label>
                <Bullets items={r.findings} />
              </section>
            )}
            {r.takeaways.length > 0 && (
              <section>
                <Label icon={<Lightbulb size={14} />}>Key takeaways</Label>
                <Bullets items={r.takeaways} />
              </section>
            )}
          </div>
        )}

        {r.limitations.length > 0 && (
          <section className="mt-6 rounded-2xl bg-warning-soft px-5 py-4">
            <h3 className="mb-2 flex items-center gap-2 text-[12px] font-semibold uppercase tracking-[0.06em] text-warning">
              <AlertTriangle size={14} /> Limitations noted
            </h3>
            <ul className="space-y-1.5 text-[14.5px] leading-relaxed text-ink-2">
              {r.limitations.map((t, i) => (
                <li key={i}>{t}</li>
              ))}
            </ul>
          </section>
        )}

        {r.key_points.length > 0 && (
          <section className="mt-8">
            <Label>Key passages</Label>
            <ul className="space-y-2.5">
              {r.key_points.map((k, i) => (
                <li key={i} className="flex gap-3 text-[15px] leading-relaxed text-ink-2">
                  <span aria-hidden className="mt-[10px] h-1 w-1 shrink-0 rounded-full bg-ink-3" />
                  <span>
                    {k.text}{' '}
                    <button
                      onClick={() => showPage(k.page)}
                      className="whitespace-nowrap text-[12.5px] font-medium text-ink-3 hover:text-accent-ink"
                    >
                      p. {k.page}
                    </button>
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-[12px] text-ink-3">Quoted from this section as written.</p>
          </section>
        )}

        <div className="mt-8">
          <Disclosure
            title="Full section text"
            aside={<span className="hidden sm:inline">{pageRange(r.page_start, r.page_end)}</span>}
          >
            <ContextView r={r} onPage={showPage} />
          </Disclosure>
          <Disclosure title="How this was scored" aside={<span className="tabular-nums">{Math.round(r.match_score * 100)} match</span>}>
            <ScoreBreakdown r={r} analysis={analysis} />
          </Disclosure>
          <div className="scroll-mt-20 border-t border-line pt-5" id="source-page">
            <h3 className="mb-3 flex items-center gap-2 text-[14px] font-semibold text-ink">
              <FileSearch size={16} className="text-ink-3" /> Source page
            </h3>
            {pdf ? (
              <PageViewer pdf={pdf} page={page} onPage={setPage} highlights={r.highlights} fileUrl={fileUrl} />
            ) : (
              <p className="text-[13px] text-ink-3">The page preview isn’t available for this file.</p>
            )}
          </div>
        </div>
      </article>
    </Card>
  )
}
