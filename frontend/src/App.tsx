import type { PDFDocumentProxy } from 'pdfjs-dist'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Analyzing } from './components/Analyzing'
import { ErrorView } from './components/ErrorView'
import { Results } from './components/Results'
import { TopNav } from './components/TopNav'
import { MAX_MB, Workspace, type FileState } from './components/Workspace'
import { AnalysisFailure, analyze, checkHealth } from './lib/api'
import { inspectPdf, releasePdf } from './lib/pdf'
import { useTheme } from './lib/theme'
import type { AnalyzeResponse, ApiError, Profile, StageName } from './lib/types'

type View = 'setup' | 'analyzing' | 'results' | 'error'

const EMPTY_PROFILE: Profile = { persona: '', expertise: 'Intermediate', objective: '', focusTerms: [] }

export default function App() {
  const { theme, toggle } = useTheme()
  const [view, setView] = useState<View>('setup')
  const [profile, setProfile] = useState<Profile>(EMPTY_PROFILE)
  const [fileState, setFileState] = useState<FileState | null>(null)
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null)
  const [fileUrl, setFileUrl] = useState<string | null>(null)
  const [online, setOnline] = useState<boolean | null>(null)
  const [stage, setStage] = useState<StageName | null>(null)
  const [stageDetails, setStageDetails] = useState<Partial<Record<StageName, string>>>({})
  const [stageDone, setStageDone] = useState(false)
  const [data, setData] = useState<AnalyzeResponse | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const abort = useRef<AbortController | null>(null)
  const inspectToken = useRef(0)

  // Backend health: poll gently, faster while offline.
  useEffect(() => {
    let timer: number
    const ctrl = new AbortController()
    const tick = async () => {
      const h = await checkHealth(ctrl.signal)
      if (ctrl.signal.aborted) return // effect was torn down (e.g. StrictMode re-run)
      setOnline(!!h)
      timer = window.setTimeout(tick, h ? 15000 : 4000)
    }
    tick()
    return () => {
      ctrl.abort()
      window.clearTimeout(timer)
    }
  }, [])

  useEffect(() => {
    window.scrollTo({ top: 0 })
  }, [view])

  const clearFile = useCallback(() => {
    inspectToken.current++
    setFileState(null)
    setPdf((old) => {
      releasePdf(old)
      return null
    })
    setFileUrl((old) => {
      if (old) URL.revokeObjectURL(old)
      return null
    })
  }, [])

  const onFile = useCallback(
    async (file: File) => {
      clearFile()
      const token = ++inspectToken.current
      const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
      if (!isPdf) {
        setFileState({ file, status: 'error', pages: null, error: 'That file isn’t a PDF. Choose a .pdf file.' })
        return
      }
      if (file.size > MAX_MB * 1024 * 1024) {
        setFileState({
          file,
          status: 'error',
          pages: null,
          error: `This PDF is larger than the ${MAX_MB} MB limit. Try a smaller file or split it.`,
        })
        return
      }
      setFileState({ file, status: 'inspecting', pages: null })
      setFileUrl(URL.createObjectURL(file))
      const res = await inspectPdf(file)
      if (token !== inspectToken.current) {
        if (res.ok) releasePdf(res.doc)
        return
      }
      if (res.ok) {
        setPdf(res.doc)
        setFileState({ file, status: 'ready', pages: res.pages })
      } else {
        setFileState({
          file,
          status: 'error',
          pages: null,
          error:
            res.reason === 'password'
              ? 'This PDF is password-protected. Remove the password (or print to a new PDF) and upload that copy.'
              : 'This file couldn’t be opened as a PDF — it may be damaged. Try re-exporting it.',
        })
      }
    },
    [clearFile],
  )

  const run = useCallback(async () => {
    if (!fileState || fileState.status !== 'ready') return
    abort.current?.abort()
    const ctrl = new AbortController()
    abort.current = ctrl
    setStage(null)
    setStageDetails({})
    setStageDone(false)
    setError(null)
    setView('analyzing')
    try {
      const result = await analyze(
        fileState.file,
        { ...profile, persona: profile.persona.trim(), objective: profile.objective.trim() },
        (e) => {
          if (e.type === 'stage') {
            setStage(e.stage)
            setStageDetails((d) => ({ ...d, [e.stage]: e.detail }))
          }
        },
        ctrl.signal,
      )
      setStageDone(true)
      setData(result)
      // Let the final checkmark register before switching views.
      await new Promise((r) => setTimeout(r, 280))
      if (!ctrl.signal.aborted) setView('results')
    } catch (e) {
      if ((e as Error).name === 'AbortError') return
      setError(
        e instanceof AnalysisFailure
          ? e.error
          : { code: 'unexpected', message: 'Something went wrong.', hint: 'Please try again.' },
      )
      setView('error')
      if (e instanceof AnalysisFailure && e.error.code === 'backend_offline') setOnline(false)
    }
  }, [fileState, profile])

  const cancel = () => {
    abort.current?.abort()
    setView('setup')
  }

  const newAnalysis = () => {
    clearFile()
    setData(null)
    setProfile((p) => ({ ...p, objective: '', focusTerms: [] }))
    setView('setup')
  }

  return (
    <div className="min-h-screen bg-bg">
      <TopNav theme={theme} onToggleTheme={toggle} online={online} onHome={() => view !== 'analyzing' && setView('setup')} />
      <main>
        {view === 'setup' && (
          <Workspace
            profile={profile}
            onProfile={setProfile}
            fileState={fileState}
            onFile={onFile}
            onRemoveFile={clearFile}
            onAnalyze={run}
            online={online}
          />
        )}
        {view === 'analyzing' && fileState && (
          <Analyzing filename={fileState.file.name} current={stage} details={stageDetails} done={stageDone} onCancel={cancel} />
        )}
        {view === 'results' && data && (
          <Results data={data} pdf={pdf} fileUrl={fileUrl} onEdit={() => setView('setup')} onNew={newAnalysis} />
        )}
        {view === 'error' && error && (
          <ErrorView
            error={error}
            onRetry={run}
            onChangeFile={() => {
              clearFile()
              setView('setup')
            }}
            onBack={() => setView('setup')}
          />
        )}
      </main>
    </div>
  )
}
