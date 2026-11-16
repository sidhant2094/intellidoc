import { AlertCircle, FileWarning, Lock, ScanLine, WifiOff } from 'lucide-react'
import type { ApiError } from '../lib/types'
import { Button, Card } from './ui'

const ICONS: Record<string, typeof AlertCircle> = {
  backend_offline: WifiOff,
  password_protected: Lock,
  scanned_pdf: ScanLine,
  no_text: FileWarning,
  malformed_pdf: FileWarning,
  invalid_file_type: FileWarning,
}

export function ErrorView({
  error,
  onRetry,
  onChangeFile,
  onBack,
}: {
  error: ApiError
  onRetry: () => void
  onChangeFile: () => void
  onBack: () => void
}) {
  const Icon = ICONS[error.code] ?? AlertCircle
  const fileProblem = ['password_protected', 'scanned_pdf', 'no_text', 'malformed_pdf', 'invalid_file_type', 'file_too_large', 'too_many_pages'].includes(error.code)
  return (
    <div className="mx-auto max-w-[540px] px-4 pb-24 pt-16 sm:pt-24 animate-fade-up">
      <Card className="p-7 text-center sm:p-10" >
        <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-danger-soft text-danger">
          <Icon size={24} strokeWidth={1.8} />
        </div>
        <h1 className="font-display text-[22px] font-semibold tracking-[-0.02em] text-ink" role="alert">
          {error.message}
        </h1>
        {error.hint && <p className="mx-auto mt-3 max-w-[420px] text-[15px] leading-relaxed text-ink-2">{error.hint}</p>}
        <div className="mt-8 flex flex-wrap justify-center gap-2">
          {fileProblem ? (
            <Button variant="primary" onClick={onChangeFile}>
              Choose another PDF
            </Button>
          ) : (
            <Button variant="primary" onClick={onRetry}>
              Try again
            </Button>
          )}
          <Button variant="ghost" onClick={onBack}>
            Back to setup
          </Button>
        </div>
        <p className="mt-6 text-[12px] text-ink-3">Error code: {error.code}</p>
      </Card>
    </div>
  )
}
