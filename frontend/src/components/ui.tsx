import type { ButtonHTMLAttributes, ReactNode } from 'react'

import { cx } from '../lib/cx'

type Variant = 'primary' | 'secondary' | 'ghost'
type Size = 'sm' | 'md' | 'lg'

export function Button({
  variant = 'secondary',
  size = 'md',
  className,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size }) {
  return (
    <button
      className={cx(
        'inline-flex select-none items-center justify-center gap-2 whitespace-nowrap font-medium transition-[background-color,color,box-shadow,transform,opacity] duration-150 active:scale-[0.985] disabled:active:scale-100',
        size === 'sm' && 'h-8 rounded-[10px] px-3 text-[13px]',
        size === 'md' && 'h-10 rounded-xl px-4 text-sm',
        size === 'lg' && 'h-12 rounded-[14px] px-5 text-[15px]',
        variant === 'primary' &&
          'bg-accent text-on-accent shadow-soft hover:bg-accent-hover disabled:bg-surface-3 disabled:text-ink-3 disabled:shadow-none',
        variant === 'secondary' &&
          'border border-line-strong bg-surface text-ink shadow-soft hover:bg-surface-2 disabled:opacity-50',
        variant === 'ghost' && 'text-ink-2 hover:bg-surface-3 hover:text-ink disabled:opacity-50',
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  )
}

export function IconButton({
  label,
  className,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      aria-label={label}
      title={label}
      className={cx(
        'inline-flex h-9 w-9 items-center justify-center rounded-[10px] text-ink-2 transition-colors hover:bg-surface-3 hover:text-ink disabled:opacity-40',
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  )
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={cx('rounded-[20px] border border-line bg-surface shadow-card', className)}>{children}</div>
  )
}

export function StepLabel({ n, children, aside }: { n: number; children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-4 flex items-center justify-between gap-3">
      <div className="flex items-center gap-2.5">
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-accent-soft text-[12px] font-semibold tabular-nums text-accent-ink">
          {n}
        </span>
        <h2 className="text-[15px] font-semibold tracking-[-0.01em] text-ink">{children}</h2>
      </div>
      {aside}
    </div>
  )
}

export function Chip({
  active,
  children,
  className,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { active?: boolean }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      className={cx(
        'inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[13px] font-medium transition-colors',
        active
          ? 'border-transparent bg-accent text-on-accent'
          : 'border-line-strong bg-surface text-ink-2 hover:border-line-strong hover:bg-surface-3 hover:text-ink',
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  )
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T
  options: { value: T; label: string; hint?: string }[]
  onChange: (v: T) => void
  label: string
}) {
  return (
    <div role="radiogroup" aria-label={label} className="grid grid-cols-3 gap-1 rounded-[14px] bg-surface-3 p-1">
      {options.map((o) => {
        const active = o.value === value
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(o.value)}
            onKeyDown={(e) => {
              const i = options.findIndex((x) => x.value === value)
              if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
                e.preventDefault()
                onChange(options[(i + 1) % options.length].value)
              } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
                e.preventDefault()
                onChange(options[(i - 1 + options.length) % options.length].value)
              }
            }}
            tabIndex={active ? 0 : -1}
            className={cx(
              'flex flex-col items-center rounded-[10px] px-2 py-2 text-center transition-all',
              active ? 'bg-surface text-ink shadow-soft' : 'text-ink-2 hover:text-ink',
            )}
          >
            <span className="text-[13px] font-semibold">{o.label}</span>
            {o.hint && <span className="mt-0.5 hidden text-[11.5px] text-ink-3 sm:block">{o.hint}</span>}
          </button>
        )
      })}
    </div>
  )
}

export function Spinner({ className }: { className?: string }) {
  return (
    <svg className={cx('animate-spin', className)} viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.2" strokeWidth="2.5" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  )
}

export function Logo() {
  return (
    <svg viewBox="0 0 32 32" className="h-7 w-7" aria-hidden>
      <rect width="32" height="32" rx="8" fill="var(--accent)" />
      <rect x="9" y="8" width="14" height="2.4" rx="1.2" fill="var(--on-accent)" />
      <rect x="9" y="13" width="9" height="2.4" rx="1.2" fill="var(--on-accent)" opacity=".7" />
      <rect x="9" y="18" width="11" height="2.4" rx="1.2" fill="var(--on-accent)" opacity=".7" />
      <circle cx="22" cy="21.5" r="3.2" fill="none" stroke="var(--on-accent)" strokeWidth="2" />
      <path d="M24.3 23.8l2 2" stroke="var(--on-accent)" strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}
