import type { PDFDocumentLoadingTask, PDFDocumentProxy } from 'pdfjs-dist'

const tasks = new WeakMap<PDFDocumentProxy, PDFDocumentLoadingTask>()

/** Free the worker-side resources held by a loaded document. */
export function releasePdf(doc: PDFDocumentProxy | null | undefined) {
  if (doc) tasks.get(doc)?.destroy()
}

let lib: Promise<typeof import('pdfjs-dist')> | null = null

async function pdfjs() {
  if (!lib) {
    lib = Promise.all([import('pdfjs-dist'), import('pdfjs-dist/build/pdf.worker.min.mjs?url')]).then(
      ([mod, worker]) => {
        mod.GlobalWorkerOptions.workerSrc = worker.default
        return mod
      },
    )
  }
  return lib
}

export type Inspection =
  | { ok: true; pages: number; doc: PDFDocumentProxy }
  | { ok: false; reason: 'password' | 'invalid' }

/** Open the PDF in the browser to show page count early and catch encrypted/invalid files. */
export async function inspectPdf(file: File): Promise<Inspection> {
  const mod = await pdfjs()
  const data = new Uint8Array(await file.arrayBuffer())
  const task = mod.getDocument({ data })
  try {
    const doc = await task.promise
    tasks.set(doc, task)
    return { ok: true, pages: doc.numPages, doc }
  } catch (e) {
    task.destroy()
    const name = (e as { name?: string }).name
    return { ok: false, reason: name === 'PasswordException' ? 'password' : 'invalid' }
  }
}
