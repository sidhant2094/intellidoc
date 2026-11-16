"""Transparent, local relevance ranking.

Final match score (0–1) is a weighted blend of five normalized signals:

  semantic      35%  TF-IDF cosine (stemmed words + bigrams, blended with character n-grams)
  keyword       25%  IDF-weighted coverage of the objective's key terms / phrases / focus terms
  content_type  20%  table/code/figure presence — only active when the objective asks for it
  expertise     15%  relative text-complexity fit to the reader's level + role-vocabulary overlap
  structure      5%  heading depth and whether the heading itself names a key term

Inactive signals have their weight redistributed. The non-topical signals (content type,
expertise, structure) are gated by topical relevance so they can re-order relevant sections
but never promote an off-topic one. The score is a *relative ranking signal*, not a probability.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

from .config import LOCAL_WEIGHTS, MAX_RESULTS, MIN_SCORE, MIN_TOPICAL, RELATIVE_FLOOR
from .sections import Chunk, Section
from .text_utils import QUERY_STOP_WORDS, analyzer, content_stems, stem, words

INTENT_PATTERNS = {
    "table": re.compile(
        r"\b(tables?|tabular|data|datasets?|statistics?|stats|numbers?|numeric|metrics?|benchmarks?|"
        r"results?|scores?|comparisons?|compare|comparing|pricing|prices?|costs?|rates?|percent(age)?s?|"
        r"budgets?|revenue|figures? for|accuracy|performance numbers|kpis?|values?|thresholds?)\b", re.I),
    "code": re.compile(
        r"\b(code|coding|snippets?|implement(ation|ing)?|apis?|endpoints?|functions?|classes|methods? signature|"
        r"syntax|commands?|cli|scripts?|config(uration)?|sdks?|librar(y|ies)|sql|queries|pseudo-?code|algorithms?)\b", re.I),
    "figure": re.compile(
        r"\b(figures?|diagrams?|charts?|graphs?|plots?|illustrations?|visuali[sz]ations?|visuals?|images?|"
        r"pictures?|flowcharts?|architecture diagram|schematics?)\b", re.I),
}

ROLE_LENSES: dict[str, list[str]] = {
    "student": ["definition", "define", "example", "introduction", "overview", "concept", "basic",
                "principle", "fundamental", "illustrate", "summary", "simple", "means"],
    "researcher": ["method", "methodology", "experiment", "evaluation", "result", "dataset", "baseline",
                   "limitation", "hypothesis", "analysis", "ablation", "finding", "contribution", "prior work"],
    "software engineer": ["implementation", "architecture", "api", "interface", "performance", "latency",
                          "complexity", "system", "deployment", "configuration", "algorithm", "memory",
                          "scalability", "parameter", "layer", "compute"],
    "product manager": ["user", "customer", "requirement", "feature", "goal", "metric", "roadmap",
                        "priority", "stakeholder", "outcome", "value", "risk", "cost", "timeline", "adoption"],
    "business analyst": ["process", "cost", "revenue", "metric", "data", "trend", "risk", "stakeholder",
                         "requirement", "kpi", "impact", "efficiency", "report", "budget", "organization"],
    "lawyer": ["shall", "must", "obligation", "liability", "right", "compliance", "regulation", "agreement",
               "party", "clause", "law", "legal", "requirement", "penalty", "governance", "policy"],
}

BEGINNER_CUES = re.compile(r"\b(introduction|overview|getting started|basics?|background|what is|"
                           r"summary|tutorial|primer|fundamentals?|preface|abstract|quick ?start)\b", re.I)
ADVANCED_CUES = re.compile(r"\b(advanced|implementation|internals?|optimi[sz]ation|proofs?|derivations?|"
                           r"theorems?|appendix|formal|specification|tuning|ablation|variations?)\b", re.I)
BOILERPLATE_WANTED = re.compile(r"\b(references?|citations?|bibliograph|acknowledg|contents|index|authors?)\b", re.I)

EXPERTISE_TARGET = {"beginner": 0.2, "intermediate": 0.5, "advanced": 0.8}


@dataclass
class Query:
    objective: str
    persona: str
    expertise: str
    focus_terms: list[str]
    key_terms: dict[str, float]  # stem -> weight
    surface: dict[str, str]  # stem -> original wording
    phrases: list[str]  # "stem stem"
    intents: set[str]
    lens_terms: list[str]  # stems
    lens_name: str | None


@dataclass
class Scored:
    chunk: Chunk
    signals: dict[str, float]
    topical: float
    score: float
    matched: list[str] = field(default_factory=list)
    complexity: float = 0.5
    lens_hits: list[str] = field(default_factory=list)
    contextual_measured: bool = False


@dataclass
class Ranked:
    section: Section
    chunks: list[Scored]  # best first
    start: int
    end: int
    score: float


def build_query(objective: str, persona: str, expertise: str, focus_terms: list[str]) -> Query:
    key: dict[str, float] = {}
    surface: dict[str, str] = {}
    toks = [w for w in words(objective)]
    content: list[str] = []
    for w in toks:
        low = w.lower()
        if low in QUERY_STOP_WORDS or len(low) < 2:
            content.append("")
            continue
        s = stem(low)
        content.append(s)
        key[s] = max(key.get(s, 0), 1.0)
        surface.setdefault(s, w if w.isupper() else low)
    phrases = [f"{a} {b}" for a, b in zip(content, content[1:]) if a and b]

    for term in focus_terms:
        stems = content_stems(term, QUERY_STOP_WORDS)
        for s, w in zip(stems, [x for x in words(term) if x.lower() not in QUERY_STOP_WORDS]):
            key[s] = 2.0
            surface.setdefault(s, w if w.isupper() else w.lower())
        if len(stems) >= 2:
            phrases += [f"{a} {b}" for a, b in zip(stems, stems[1:])]

    intent_text = objective + " " + " ".join(focus_terms)
    intents = {name for name, pat in INTENT_PATTERNS.items() if pat.search(intent_text)}

    p = persona.lower().strip()
    lens_name = next((name for name in ROLE_LENSES if name in p or p in name and len(p) > 3), None)
    lens: list[str] = []
    if lens_name:
        lens = [stem(w) for w in ROLE_LENSES[lens_name] if " " not in w]
    lens += [s for s in content_stems(persona, QUERY_STOP_WORDS) if s not in lens and len(s) > 2]

    return Query(objective, persona, expertise.lower(), focus_terms, key, surface,
                 list(dict.fromkeys(phrases)), intents, lens, lens_name)


def _doc_text(c: Chunk) -> str:
    sec = c.section
    return f"{sec.title} {sec.title} {' '.join(sec.path[:-1])}\n{c.text}"


def _complexity(text: str, title: str) -> float:
    ws = text.split()
    if not ws:
        return 0.5
    sents = max(1, len(re.findall(r"[.!?](\s|$)", text)))
    asl = min(1.0, max(0.0, (len(ws) / sents - 10) / 25))
    long_ratio = min(1.0, max(0.0, (sum(1 for w in ws if len(w) >= 10) / len(ws) - 0.04) / 0.14))
    sym = min(1.0, len(re.findall(r"[=+×∑√∫≤≥≈∈λμσθαβγδεπ^_{}\\]|\d", text)) / max(1, len(text)) / 0.04)
    acr = min(1.0, sum(1 for w in ws if re.fullmatch(r"[A-Z]{2,}[a-z]?s?", w)) / len(ws) / 0.06)
    cue = 0.0
    if BEGINNER_CUES.search(title):
        cue -= 0.25
    if ADVANCED_CUES.search(title):
        cue += 0.25
    return (asl + long_ratio + sym + acr) / 4 + cue


SIGNALS = ("semantic", "keyword", "content_type", "expertise", "structure", "contextual")
TOPICAL = ("semantic", "keyword", "contextual")


def compute_signals(chunks: list[Chunk], q: Query) -> tuple[list[Scored], np.ndarray]:
    """Per-chunk local signals. `semantic` starts as the TF-IDF proxy; `contextual` starts unmeasured.

    Returns the scored chunks and the raw TF-IDF similarity (used as a recall prefilter).
    """
    docs = [_doc_text(c) for c in chunks]
    qtext = q.objective + " " + " ".join(q.focus_terms * 2)

    wvec = TfidfVectorizer(analyzer=analyzer, sublinear_tf=True, norm="l2")
    W = wvec.fit_transform(docs)
    qW = wvec.transform([qtext])
    word_cos = linear_kernel(qW, W).ravel()

    cvec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, max_features=150_000)
    C = cvec.fit_transform([d.lower() for d in docs])
    qC = cvec.transform([qtext.lower()])
    char_cos = linear_kernel(qC, C).ravel()
    # Character similarity has a high floor between any two English texts; remove it.
    char_adj = np.clip(char_cos - np.median(char_cos), 0, None)

    sem_raw = 0.75 * word_cos + 0.25 * char_adj
    sem = np.clip(sem_raw / max(float(sem_raw.max()), 0.30), 0, 1)

    vocab = wvec.vocabulary_
    idf = wvec.idf_
    max_idf = float(idf.max()) if len(idf) else 1.0

    def term_idf(s: str) -> float:
        i = vocab.get(s)
        return float(idf[i]) if i is not None else max_idf

    key_items = [(s, w * term_idf(s)) for s, w in q.key_terms.items()]
    key_den = sum(w for _, w in key_items) or 1.0

    stems_per_chunk = [content_stems(d) for d in docs]
    comp_pct = _percentiles([_complexity(c.text, c.section.title) for c in chunks])
    target = EXPERTISE_TARGET.get(q.expertise, 0.5)

    scored: list[Scored] = []
    for i, c in enumerate(chunks):
        st = stems_per_chunk[i]
        counts: dict[str, int] = {}
        for s in st:
            counts[s] = counts.get(s, 0) + 1
        bigrams = {f"{a} {b}" for a, b in zip(st, st[1:])}

        matched = [s for s, _ in key_items if counts.get(s)]
        cov = sum(w * min(1.0, 0.6 + 0.2 * counts[s]) for s, w in key_items if counts.get(s)) / key_den
        if q.phrases:
            cov += 0.15 * sum(1 for p in q.phrases if p in bigrams) / len(q.phrases)
        kw = min(1.0, cov) if q.key_terms else float(sem[i])

        ct = 1.0 if (q.intents and c.content_types & q.intents) else 0.0

        fit = 1 - abs(comp_pct[i] - target)
        lens_hits = [s for s in q.lens_terms if counts.get(s)]
        lens = min(1.0, len(lens_hits) / 4) if q.lens_terms else None
        exp = fit if lens is None else 0.6 * fit + 0.4 * lens

        title_stems = set(content_stems(c.section.title))
        level_score = {1: 1.0, 2: 0.85}.get(c.section.level, 0.7)
        struct = 1.0 if title_stems & set(q.key_terms) else level_score
        if c.section.boilerplate:
            struct = 0.0

        signals = {"semantic": float(sem[i]), "keyword": float(kw), "content_type": ct,
                   "expertise": float(exp), "structure": struct, "contextual": 0.0}
        scored.append(Scored(c, signals, 0.0, 0.0, matched, comp_pct[i], lens_hits))
    return scored, sem_raw


def combine(scored: list[Scored], q: Query, weights: dict[str, float]) -> dict[str, float]:
    """Blend signals into scores in place. Returns the normalized weights actually used.

    Inactive signals (weight 0, or content type when no type was requested) are redistributed.
    Topical signals (semantic, keyword, contextual) gate the others so content type, expertise
    and structure can re-order relevant passages but never promote an off-topic one.
    """
    w = {k: float(weights.get(k, 0.0)) for k in SIGNALS}
    if not q.intents:
        w["content_type"] = 0.0
    total = sum(w.values()) or 1.0
    w = {k: v / total for k, v in w.items()}
    tsum = sum(w[k] for k in TOPICAL) or 1.0
    wants_boiler = bool(BOILERPLATE_WANTED.search(q.objective + " " + " ".join(q.focus_terms)))

    for s in scored:
        sig = s.signals
        topical_part = sum(w[k] * sig[k] for k in TOPICAL)
        s.topical = topical_part / tsum
        gate = min(1.0, s.topical / 0.4)
        s.score = topical_part + gate * (
            w["content_type"] * sig["content_type"] + w["expertise"] * sig["expertise"] + w["structure"] * sig["structure"]
        )
        if s.chunk.section.boilerplate and not wants_boiler:
            s.score *= 0.35
    return w


def rank(chunks: list[Chunk], q: Query) -> tuple[list[Ranked], dict]:
    """The original local engine (no external services)."""
    if not chunks:
        return [], {}
    scored, _ = compute_signals(chunks, q)
    w = combine(scored, q, LOCAL_WEIGHTS)
    ranked = aggregate(scored, q)
    return ranked, meta_for(scored, q, w)


def meta_for(scored: list[Scored], q: Query, w: dict[str, float]) -> dict:
    return {
        "weights": {k: round(v, 4) for k, v in w.items()},
        "content_type_active": bool(q.intents),
        "intents": sorted(q.intents),
        "candidates": sum(1 for s in scored if passes(s, q)),
    }


def passes(s: Scored, q: Query, relaxed: bool = False) -> bool:
    factor = 0.6 if relaxed else 1.0
    if s.topical < MIN_TOPICAL * factor or s.score < MIN_SCORE * factor:
        return False
    if s.contextual_measured and s.signals["contextual"] <= 0.0:
        return False  # judged not useful for this objective
    if (q.key_terms and not s.matched and s.signals["semantic"] < 0.5
            and not (s.contextual_measured and s.signals["contextual"] >= 0.6)):
        return False
    return True


def aggregate(scored: list[Scored], q: Query, limit: int = MAX_RESULTS, relaxed: bool = False) -> list[Ranked]:
    by_section: dict[str, list[Scored]] = {}
    for s in scored:
        if passes(s, q, relaxed):
            by_section.setdefault(s.chunk.section.id, []).append(s)

    ranked: list[Ranked] = []
    for items in by_section.values():
        items.sort(key=lambda s: -s.score)
        best = items[0]
        group = [best]
        # Merge adjacent strong chunks from the same section into one coherent passage.
        for other in items[1:]:
            if other.score >= 0.85 * best.score and any(abs(other.chunk.id - g.chunk.id) == 1 for g in group):
                group.append(other)
        start = min(g.chunk.start for g in group)
        end = max(g.chunk.end for g in group)
        bonus = 0.02 * min(2, len(items) - 1)
        ranked.append(Ranked(best.chunk.section, sorted(group, key=lambda s: -s.score), start, end,
                             min(1.0, best.score + bonus)))

    ranked.sort(key=lambda r: -r.score)
    if not ranked:
        return []
    if not relaxed:
        top = ranked[0].score
        ranked = [r for r in ranked if r.score >= RELATIVE_FLOOR * top]

    final: list[Ranked] = []
    shingles: list[set[str]] = []
    for r in ranked:
        sh = _shingles(r.section.text[r.start:r.end])
        if any(_jaccard(sh, o) > 0.5 for o in shingles):
            continue
        final.append(r)
        shingles.append(sh)
        if len(final) >= limit:
            break
    return final


def _shingles(text: str, n: int = 5) -> set[str]:
    ws = text.lower().split()
    return {" ".join(ws[i:i + n]) for i in range(max(1, len(ws) - n + 1))}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _percentiles(values: list[float]) -> list[float]:
    if len(values) == 1:
        return [0.5]
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    for r, i in enumerate(order):
        out[i] = r / (len(values) - 1)
    return out


def relevance_label(score: float) -> str:
    if score >= 0.62:
        return "Highly relevant"
    if score >= 0.45:
        return "Relevant"
    return "Somewhat relevant"


__all__ = ["Query", "Ranked", "Scored", "aggregate", "build_query", "combine", "compute_signals", "passes", "rank", "relevance_label"]
