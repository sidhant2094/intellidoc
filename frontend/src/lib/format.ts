import type { AnalyzeResponse } from './types'

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export function pageRange(a: number, b: number, long = false): string {
  if (a === b) return long ? `Page ${a}` : `p. ${a}`
  return long ? `Pages ${a}–${b}` : `pp. ${a}–${b}`
}

export function formatDuration(ms: number): string {
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`
}

export function scorePct(score: number): number {
  return Math.round(score * 100)
}

export function toMarkdown(data: AnalyzeResponse): string {
  const { document: d, analysis: a, results } = data
  const lines: string[] = [
    `# Reading path — ${d.filename}`,
    '',
    `- **Reader:** ${a.persona} (${a.expertise})`,
    `- **Objective:** ${a.objective}`,
    a.focus_terms.length ? `- **Focus terms:** ${a.focus_terms.join(', ')}` : '',
    `- **Document:** ${d.page_count} pages, ${d.section_count} sections`,
    '',
    '> Match scores are relative ranking signals within this document, not probabilities.',
    '',
  ].filter((l, i, arr) => l !== '' || arr[i - 1] !== '')

  for (const r of results) {
    lines.push(
      `## ${r.rank}. ${r.title}`,
      '',
      `${r.breadcrumb.length > 1 ? `*${r.breadcrumb.join(' › ')}* · ` : ''}${pageRange(r.page_start, r.page_end, true)} · ${r.relevance_label} (match ${scorePct(r.match_score)})`,
      '',
      `**Why it’s relevant:** ${r.why_relevant}`,
      '',
      `> ${r.excerpt}`,
      `> — page ${r.excerpt_page}`,
      '',
    )
    if (r.summary) lines.push(`**Summary:** ${r.summary}`, '')
    for (const [label, items] of [
      ['Important findings', r.findings],
      ['Key takeaways', r.takeaways],
      ['Limitations noted', r.limitations],
    ] as const) {
      if (items.length) {
        lines.push(`**${label}:**`, '', ...items.map((t) => `- ${t}`), '')
      }
    }
    if (r.key_points.length) {
      lines.push('**Key passages (verbatim):**', '')
      for (const k of r.key_points) lines.push(`- ${k.text} *(p. ${k.page})*`)
      lines.push('')
    }
  }
  if (data.insights.length) {
    lines.push('## Top insights', '')
    for (const ins of data.insights) {
      const refs = ins.result_ids
        .map((id) => results.find((r) => r.id === id))
        .filter(Boolean)
        .map((r) => `#${r!.rank} (${pageRange(r!.page_start, r!.page_end)})`)
      lines.push(`- **${ins.title}** — ${ins.text}${refs.length ? ` ${refs.join(', ')}` : ''}`)
    }
    lines.push('')
  }
  if (!results.length) lines.push('_No sufficiently relevant sections were found._')
  return lines.join('\n')
}

export function download(filename: string, text: string, type = 'text/markdown') {
  const url = URL.createObjectURL(new Blob([text], { type }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
