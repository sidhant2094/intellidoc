import { Moon, Sun, X } from 'lucide-react'
import { useRef } from 'react'
import type { Theme } from '../lib/theme'
import { Button, IconButton, Logo } from './ui'

export function TopNav({
  theme,
  onToggleTheme,
  online,
  onHome,
}: {
  theme: Theme
  onToggleTheme: () => void
  online: boolean | null
  onHome: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-bg/85 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-[1440px] items-center justify-between px-4 sm:px-6 lg:px-8">
        <button onClick={onHome} className="flex items-center gap-2.5 rounded-lg" aria-label="IntelliDoc home">
          <Logo />
          <span className="font-display text-[17px] font-semibold tracking-[-0.02em] text-ink">IntelliDoc</span>
        </button>
        <div className="flex items-center gap-1 sm:gap-2">
          <EngineStatus online={online} />
          <Button variant="ghost" size="sm" onClick={() => dialog.current?.showModal()}>
            How it works
          </Button>
          <IconButton
            label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            onClick={onToggleTheme}
          >
            {theme === 'dark' ? <Sun size={18} strokeWidth={1.8} /> : <Moon size={18} strokeWidth={1.8} />}
          </IconButton>
        </div>
      </div>
      <HowItWorks dialogRef={dialog} />
    </header>
  )
}

function EngineStatus({ online }: { online: boolean | null }) {
  // Only surfaced when the app's own server can't be reached — never which engine is in use.
  if (online !== false) return null
  return (
    <span
      className="mr-1 hidden items-center gap-2 rounded-full bg-danger-soft px-2.5 py-1 text-[12.5px] font-medium text-danger sm:inline-flex"
      role="status"
      title="The server may be starting up; retrying automatically"
    >
      <span className="h-1.5 w-1.5 rounded-full bg-danger" />
      Can’t reach IntelliDoc
    </span>
  )
}

const STEPS = [
  ['Read', 'Text is extracted page by page. Running headers, footers and page numbers are removed; scanned pages are flagged.'],
  ['Structure', 'Sections come from the PDF’s bookmarks when present, otherwise from its typography. Long sections are split into overlapping passages that keep their exact pages.'],
  ['Understand', 'Each passage is compared with what you’re looking for — by meaning, not just matching words — and weighed against your role and level.'],
  ['Rank & explain', 'The strongest sections are de-duplicated and explained. You get up to 10 — fewer when fewer are genuinely relevant.'],
] as const

const SIGNALS = [
  ['Meaning similarity', 'How closely a passage’s meaning matches your objective'],
  ['Keyword coverage', 'How many of your key terms and focus terms it contains'],
  ['Contextual relevance', 'Whether the passage is actually useful for your objective, judged from its content'],
  ['Content type', 'Tables, code or figures — only when your objective asks for them'],
  ['Expertise fit', 'How well its complexity suits your level and role'],
  ['Structure', 'Heading depth, and whether the heading names your topic'],
] as const

function HowItWorks({ dialogRef }: { dialogRef: React.RefObject<HTMLDialogElement | null> }) {
  return (
    <dialog
      ref={dialogRef}
      className="m-auto w-[min(640px,calc(100vw-32px))] rounded-[22px] border border-line bg-surface p-0 text-ink shadow-lift"
      onClick={(e) => {
        if (e.target === dialogRef.current) dialogRef.current?.close()
      }}
    >
      <div className="max-h-[85vh] overflow-y-auto p-6 sm:p-8 scroll-thin">
        <div className="mb-6 flex items-start justify-between gap-4">
          <div>
            <h2 className="font-display text-2xl font-semibold tracking-[-0.02em]">How IntelliDoc works</h2>
            <p className="mt-1 text-sm text-ink-2">From a long PDF to a short, verifiable reading path.</p>
          </div>
          <IconButton label="Close" onClick={() => dialogRef.current?.close()}>
            <X size={18} />
          </IconButton>
        </div>
        <ol className="space-y-4">
          {STEPS.map(([title, text], i) => (
            <li key={title} className="flex gap-4">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent-soft text-[12px] font-semibold text-accent-ink">
                {i + 1}
              </span>
              <div>
                <div className="text-[14px] font-semibold">{title}</div>
                <p className="text-[13.5px] leading-relaxed text-ink-2">{text}</p>
              </div>
            </li>
          ))}
        </ol>
        <div className="mt-7 overflow-hidden rounded-2xl border border-line">
          {SIGNALS.map(([name, desc]) => (
            <div key={name} className="border-b border-line px-4 py-3 last:border-0">
              <div className="text-[13.5px] font-medium">{name}</div>
              <div className="text-[12.5px] text-ink-2">{desc}</div>
            </div>
          ))}
        </div>
        <div className="mt-5 space-y-3 text-[12.5px] leading-relaxed text-ink-3">
          <p>
            The match score ranks sections within one document — it isn’t a probability or a measure of factual
            confidence. Quoted excerpts are copied verbatim from the PDF and highlighted on the page so you can check
            them. Summaries and answers are written from the retrieved passages and cite where they come from.
          </p>
          <p>
            <span className="font-medium text-ink-2">Privacy.</span> IntelliDoc doesn’t save your PDF; it’s held in
            memory only while you work with it. Depending on how IntelliDoc is set up, passages from your document and
            your questions may be sent to an external AI service for analysis, under that service’s terms.
          </p>
        </div>
      </div>
    </dialog>
  )
}
