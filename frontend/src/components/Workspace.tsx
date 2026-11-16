import { AlertCircle, ArrowRight, FileText, Lock, RefreshCw, ShieldCheck, Trash2, UploadCloud, X } from 'lucide-react'
import { useId, useRef, useState } from 'react'
import { formatBytes } from '../lib/format'
import type { Expertise, Profile } from '../lib/types'
import { Button, Card, Chip, Segmented, Spinner, StepLabel } from './ui'
import { cx } from '../lib/cx'

export interface FileState {
  file: File
  status: 'inspecting' | 'ready' | 'error'
  pages: number | null
  error?: string
}

export const MAX_MB = 30

const PRESETS: { name: string; example: string }[] = [
  { name: 'Student', example: 'Explain the core ideas I need to understand, starting from the basics' },
  { name: 'Researcher', example: 'Methodology, evaluation results and stated limitations' },
  { name: 'Software Engineer', example: 'Architecture, implementation details and performance constraints' },
  { name: 'Product Manager', example: 'User-facing capabilities, success metrics and rollout risks' },
  { name: 'Business Analyst', example: 'Costs, KPIs and process changes with their business impact' },
  { name: 'Lawyer', example: 'Obligations, liabilities and compliance requirements' },
]

const EXPERTISE: { value: Expertise; label: string; hint: string }[] = [
  { value: 'Beginner', label: 'Beginner', hint: 'New to the topic' },
  { value: 'Intermediate', label: 'Intermediate', hint: 'Working knowledge' },
  { value: 'Advanced', label: 'Advanced', hint: 'Deep expertise' },
]

export function Workspace({
  profile,
  onProfile,
  fileState,
  onFile,
  onRemoveFile,
  onAnalyze,
  online,
}: {
  profile: Profile
  onProfile: (p: Profile) => void
  fileState: FileState | null
  onFile: (f: File) => void
  onRemoveFile: () => void
  onAnalyze: () => void
  online: boolean | null
}) {
  const set = <K extends keyof Profile>(k: K, v: Profile[K]) => onProfile({ ...profile, [k]: v })
  const preset = PRESETS.find((p) => p.name === profile.persona)
  const placeholder = preset ? `e.g. ${preset.example}` : 'e.g. Deployment requirements and the limits I need to plan around'

  const missing: string[] = []
  if (!profile.persona.trim()) missing.push('your role')
  if (profile.objective.trim().length < 3) missing.push('your objective')
  if (!fileState) missing.push('a PDF')
  const fileOk = fileState?.status === 'ready'
  const canAnalyze = missing.length === 0 && fileOk && online !== false

  return (
    <div className="mx-auto max-w-[1180px] px-4 pb-20 pt-10 sm:px-6 sm:pt-16 lg:px-8">
      <section className="mx-auto mb-10 max-w-[720px] text-center sm:mb-14 animate-fade-up">
        <p className="mb-4 text-[13px] font-medium tracking-wide text-accent-ink">Persona-aware PDF intelligence</p>
        <h1 className="font-display text-[40px] font-semibold leading-[1.05] tracking-[-0.035em] text-ink sm:text-[56px]">
          Find what matters.
          <br />
          <span className="text-ink-3">Skip what doesn’t.</span>
        </h1>
        <p className="mx-auto mt-5 max-w-[560px] text-[17px] leading-relaxed text-ink-2">
          Tell IntelliDoc who you are and what you need. Get a ranked reading path through any long PDF — with exact
          pages and quotes you can verify.
        </p>
      </section>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)] lg:gap-6">
        <Card className="p-5 sm:p-7 animate-fade-up [animation-delay:60ms]">
          <StepLabel n={1}>Who’s reading</StepLabel>
          <div className="flex flex-wrap gap-2" role="group" aria-label="Role presets">
            {PRESETS.map((p) => (
              <Chip key={p.name} active={profile.persona === p.name} onClick={() => set('persona', p.name)}>
                {p.name}
              </Chip>
            ))}
            <Chip
              active={!!profile.persona && !preset}
              onClick={() => {
                if (preset) set('persona', '')
                document.getElementById('persona-input')?.focus()
              }}
            >
              Other
            </Chip>
          </div>
          <label htmlFor="persona-input" className="mt-4 block text-[13px] font-medium text-ink-2">
            Your role
          </label>
          <input
            id="persona-input"
            value={profile.persona}
            onChange={(e) => set('persona', e.target.value)}
            placeholder="e.g. Security auditor, Medical student, Founder"
            maxLength={120}
            className="mt-1.5 h-11 w-full rounded-xl border border-line-strong bg-surface-2 px-3.5 text-[15px] text-ink outline-none transition-colors placeholder:text-ink-3 focus:border-accent focus:bg-surface focus:ring-4 focus:ring-accent-soft"
          />
          <div className="mt-5">
            <div className="mb-1.5 text-[13px] font-medium text-ink-2" id="expertise-label">
              Expertise
            </div>
            <Segmented label="Expertise" value={profile.expertise} options={EXPERTISE} onChange={(v) => set('expertise', v)} />
          </div>

          <div className="my-7 h-px bg-line" />

          <StepLabel n={2}>What are you trying to find?</StepLabel>
          <textarea
            aria-label="Your objective"
            value={profile.objective}
            onChange={(e) => set('objective', e.target.value)}
            placeholder={placeholder}
            rows={4}
            maxLength={2000}
            className="w-full resize-none rounded-2xl border border-line-strong bg-surface-2 px-4 py-3.5 text-[16px] leading-relaxed text-ink outline-none transition-colors placeholder:text-ink-3 focus:border-accent focus:bg-surface focus:ring-4 focus:ring-accent-soft"
          />
          {preset && !profile.objective && (
            <button
              type="button"
              onClick={() => set('objective', preset.example)}
              className="mt-2 inline-flex items-center gap-1.5 rounded-lg text-[13px] text-accent-ink hover:underline"
            >
              Use this example <ArrowRight size={13} />
            </button>
          )}
          <p className="mt-2 text-[12.5px] text-ink-3">
            Be specific — name topics rather than goals. The objective drives the ranking; your role and level refine it.
          </p>
          <FocusTerms terms={profile.focusTerms} onChange={(t) => set('focusTerms', t)} />
        </Card>

        <div className="flex flex-col gap-5 lg:gap-6">
          <Card className="p-5 sm:p-7 animate-fade-up [animation-delay:120ms]">
            <StepLabel n={3}>Your document</StepLabel>
            {fileState ? (
              <FileCard state={fileState} onRemove={onRemoveFile} onReplace={onFile} />
            ) : (
              <Dropzone onFile={onFile} />
            )}
            <p className="mt-4 flex items-start gap-2 text-[12.5px] leading-relaxed text-ink-3">
              <ShieldCheck size={15} className="mt-px shrink-0" />
              IntelliDoc doesn’t save your PDF — it’s held in memory only while you work with it. Privacy details
              are in “How it works”.
            </p>
          </Card>

          <div className="lg:sticky lg:top-20 animate-fade-up [animation-delay:180ms]">
            <Button
              variant="primary"
              size="lg"
              className="w-full"
              disabled={!canAnalyze}
              onClick={onAnalyze}
            >
              Find relevant sections
              <ArrowRight size={18} />
            </Button>
            <p className="mt-2.5 min-h-5 text-center text-[13px] text-ink-3" aria-live="polite">
              {online === false
                ? 'Can’t reach IntelliDoc — start the server with ./start.sh'
                : missing.length
                  ? `Add ${joinList(missing)} to continue`
                  : fileState?.status === 'inspecting'
                    ? 'Reading the file…'
                    : fileState?.status === 'error'
                      ? 'Choose a different PDF to continue'
                      : 'Ready when you are'}
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

function joinList(items: string[]) {
  return items.length < 2 ? items.join('') : `${items.slice(0, -1).join(', ')} and ${items.at(-1)}`
}

function FocusTerms({ terms, onChange }: { terms: string[]; onChange: (t: string[]) => void }) {
  const [draft, setDraft] = useState('')
  const id = useId()
  const add = (raw: string) => {
    const next = raw
      .split(',')
      .map((t) => t.trim())
      .filter((t) => t && !terms.some((x) => x.toLowerCase() === t.toLowerCase()))
    if (next.length) onChange([...terms, ...next].slice(0, 12))
    setDraft('')
  }
  return (
    <div className="mt-5">
      <label htmlFor={id} className="text-[13px] font-medium text-ink-2">
        Focus terms <span className="font-normal text-ink-3">· optional</span>
      </label>
      <div className="mt-1.5 flex min-h-11 flex-wrap items-center gap-1.5 rounded-xl border border-line-strong bg-surface-2 px-2 py-1.5 transition-colors focus-within:border-accent focus-within:bg-surface focus-within:ring-4 focus-within:ring-accent-soft">
        {terms.map((t) => (
          <span key={t} className="inline-flex h-7 items-center gap-1 rounded-lg bg-accent-soft pl-2.5 pr-1 text-[13px] font-medium text-accent-ink">
            {t}
            <button
              type="button"
              aria-label={`Remove ${t}`}
              onClick={() => onChange(terms.filter((x) => x !== t))}
              className="flex h-5 w-5 items-center justify-center rounded-md hover:bg-accent-soft-2"
            >
              <X size={12} />
            </button>
          </span>
        ))}
        <input
          id={id}
          value={draft}
          onChange={(e) => (e.target.value.endsWith(',') ? add(e.target.value) : setDraft(e.target.value))}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              add(draft)
            } else if (e.key === 'Backspace' && !draft && terms.length) {
              onChange(terms.slice(0, -1))
            }
          }}
          onBlur={() => draft && add(draft)}
          placeholder={terms.length ? '' : 'Keywords that must count extra — press Enter'}
          className="h-7 min-w-[160px] flex-1 bg-transparent px-1.5 text-[14px] text-ink outline-none placeholder:text-ink-3"
        />
      </div>
    </div>
  )
}

function Dropzone({ onFile }: { onFile: (f: File) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  return (
    <div
      onDragOver={(e) => {
        e.preventDefault()
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setOver(false)
        const f = e.dataTransfer.files[0]
        if (f) onFile(f)
      }}
      className={cx(
        'flex flex-col items-center justify-center rounded-2xl border-[1.5px] border-dashed px-6 py-12 text-center transition-colors',
        over ? 'border-accent bg-accent-soft' : 'border-line-strong bg-surface-2',
      )}
    >
      <div className={cx('mb-4 flex h-12 w-12 items-center justify-center rounded-2xl transition-colors', over ? 'bg-accent text-on-accent' : 'bg-accent-soft text-accent-ink')}>
        <UploadCloud size={22} strokeWidth={1.8} />
      </div>
      <p className="text-[15px] font-semibold text-ink">{over ? 'Release to add your PDF' : 'Drop a PDF here'}</p>
      <p className="mt-1 text-[13px] text-ink-3">Up to {MAX_MB} MB · digital PDFs work best</p>
      <Button size="sm" className="mt-5" onClick={() => input.current?.click()}>
        Browse files
      </Button>
      <input
        ref={input}
        type="file"
        accept="application/pdf,.pdf"
        className="sr-only"
        tabIndex={-1}
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) onFile(f)
          e.target.value = ''
        }}
      />
    </div>
  )
}

function FileCard({ state, onRemove, onReplace }: { state: FileState; onRemove: () => void; onReplace: (f: File) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const error = state.status === 'error'
  return (
    <div
      className={cx(
        'rounded-2xl border p-4 transition-colors animate-fade-in',
        error ? 'border-danger/30 bg-danger-soft' : 'border-line bg-surface-2',
      )}
    >
      <div className="flex items-start gap-3.5">
        <div
          className={cx(
            'flex h-11 w-11 shrink-0 items-center justify-center rounded-xl',
            error ? 'bg-danger-soft text-danger' : 'bg-accent-soft text-accent-ink',
          )}
        >
          {state.error?.includes('password') ? <Lock size={20} /> : error ? <AlertCircle size={20} /> : <FileText size={20} strokeWidth={1.8} />}
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[15px] font-semibold text-ink" title={state.file.name}>
            {state.file.name}
          </p>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[13px] text-ink-3">
            <span>{formatBytes(state.file.size)}</span>
            {state.pages != null && (
              <>
                <span aria-hidden>·</span>
                <span>
                  {state.pages} page{state.pages === 1 ? '' : 's'}
                </span>
              </>
            )}
            {state.status === 'inspecting' && (
              <span className="inline-flex items-center gap-1.5">
                <span aria-hidden>·</span>
                <Spinner className="h-3.5 w-3.5" /> Checking
              </span>
            )}
            {state.status === 'ready' && (
              <span className="inline-flex items-center gap-1.5 text-success">
                <span aria-hidden className="text-ink-3">·</span>
                <span className="h-1.5 w-1.5 rounded-full bg-success" />
                Ready
              </span>
            )}
          </p>
          {error && <p className="mt-2 text-[13px] leading-relaxed text-danger">{state.error}</p>}
        </div>
      </div>
      <div className="mt-4 flex gap-2">
        <Button size="sm" onClick={() => input.current?.click()}>
          <RefreshCw size={14} /> Replace
        </Button>
        <Button size="sm" variant="ghost" onClick={onRemove}>
          <Trash2 size={14} /> Remove
        </Button>
      </div>
      <input
        ref={input}
        type="file"
        accept="application/pdf,.pdf"
        className="sr-only"
        tabIndex={-1}
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) onReplace(f)
          e.target.value = ''
        }}
      />
    </div>
  )
}
