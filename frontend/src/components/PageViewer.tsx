import { ChevronLeft, ChevronRight, ExternalLink } from 'lucide-react'
import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist'
import { useEffect, useRef, useState } from 'react'
import type { Highlight } from '../lib/types'
import { IconButton, Spinner } from './ui'

export function PageViewer({
  pdf,
  page,
  onPage,
  highlights,
  fileUrl,
}: {
  pdf: PDFDocumentProxy | null
  page: number
  onPage: (p: number) => void
  highlights: Highlight[]
  fileUrl: string | null
}) {
  const wrap = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const [width, setWidth] = useState(0)
  const [aspect, setAspect] = useState(1.294)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const total = pdf?.numPages ?? 0

  useEffect(() => {
    const el = wrap.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    if (!pdf || !width || !canvas.current) return
    let task: RenderTask | null = null
    let cancelled = false
    setStatus('loading')
    ;(async () => {
      try {
        const p = await pdf.getPage(page)
        if (cancelled) return
        const base = p.getViewport({ scale: 1 })
        setAspect(base.height / base.width)
        const dpr = Math.min(window.devicePixelRatio || 1, 2.5)
        const viewport = p.getViewport({ scale: (width / base.width) * dpr })
        const c = canvas.current!
        c.width = Math.floor(viewport.width)
        c.height = Math.floor(viewport.height)
        task = p.render({ canvas: c, viewport })
        await task.promise
        if (!cancelled) setStatus('ready')
      } catch (e) {
        if (!cancelled && (e as Error).name !== 'RenderingCancelledException') setStatus('error')
      }
    })()
    return () => {
      cancelled = true
      task?.cancel()
    }
  }, [pdf, page, width])

  const rects = highlights.find((h) => h.page === page)?.rects ?? []

  return (
    <div>
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          <IconButton label="Previous page" disabled={page <= 1} onClick={() => onPage(page - 1)}>
            <ChevronLeft size={17} />
          </IconButton>
          <span className="min-w-[92px] text-center text-[13px] tabular-nums text-ink-2">
            Page {page}
            {total ? <span className="text-ink-3"> of {total}</span> : null}
          </span>
          <IconButton label="Next page" disabled={!total || page >= total} onClick={() => onPage(page + 1)}>
            <ChevronRight size={17} />
          </IconButton>
        </div>
        {fileUrl && (
          <a
            href={`${fileUrl}#page=${page}`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[13px] font-medium text-accent-ink hover:bg-accent-soft"
          >
            Open original <ExternalLink size={13} />
          </a>
        )}
      </div>
      <div
        ref={wrap}
        className="relative overflow-hidden rounded-xl border border-line bg-white shadow-soft"
        style={{ aspectRatio: `1 / ${aspect}` }}
      >
        <canvas
          ref={canvas}
          className="block h-full w-full transition-opacity duration-200"
          style={{ filter: 'var(--paper-filter)', opacity: status === 'ready' ? 1 : 0.35 }}
          aria-label={`Rendered page ${page} of the PDF`}
          role="img"
        />
        {status === 'ready' &&
          rects.map(([x0, y0, x1, y1], i) => (
            <span
              key={i}
              aria-hidden
              className="pointer-events-none absolute rounded-[2px] mix-blend-multiply"
              style={{
                left: `${x0 * 100}%`,
                top: `${y0 * 100}%`,
                width: `${(x1 - x0) * 100}%`,
                height: `${(y1 - y0) * 100}%`,
                background: 'rgb(255 196 0 / 0.38)',
              }}
            />
          ))}
        {status === 'loading' && (
          <div className="absolute inset-0 flex items-center justify-center text-neutral-400">
            <Spinner className="h-5 w-5" />
          </div>
        )}
        {status === 'error' && (
          <div className="absolute inset-0 flex items-center justify-center p-6 text-center text-[13px] text-neutral-500">
            This page couldn’t be rendered in the browser. Use “Open original”.
          </div>
        )}
      </div>
      {rects.length > 0 && status === 'ready' && (
        <p className="mt-2 text-[12px] text-ink-3">Highlighted: where the excerpt appears on this page.</p>
      )}
    </div>
  )
}
