"""Tunable limits and ranking weights (documented in README)."""

MAX_FILE_MB = 30
MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024
MAX_PAGES = 1500
TABLE_DETECTION_BUDGET_S = 4.0

# Chunking (words)
CHUNK_WORDS = 600
CHUNK_OVERLAP = 120
SPLIT_THRESHOLD_WORDS = 800  # sections at or below this size stay whole

MAX_RESULTS = 10

# Local engine (original IntelliDoc weights). Signals that cannot be measured for a request
# (content type when the objective names no table/code/figure need; contextual relevance without a
# reasoning model) have their weight redistributed proportionally — never filled with a fake value.
LOCAL_WEIGHTS = {
    "semantic": 0.35,      # TF-IDF similarity proxy
    "keyword": 0.25,
    "content_type": 0.20,
    "expertise": 0.15,
    "structure": 0.05,
    "contextual": 0.0,
}

# Hybrid engine: `semantic` is embedding similarity (TF-IDF is then used only for recall, so
# semantic similarity is not counted twice); `contextual` is the reranker's usefulness judgment.
HYBRID_WEIGHTS = {
    "semantic": 0.35,
    "keyword": 0.20,
    "content_type": 0.15,
    "expertise": 0.10,
    "structure": 0.05,
    "contextual": 0.15,
}
WEIGHTS = LOCAL_WEIGHTS  # backward-compatible name

RERANK_CANDIDATES = 24

# Thresholds on the 0–1 match score
MIN_TOPICAL = 0.16       # topical (semantic+keyword) floor
MIN_SCORE = 0.28         # final score floor
RELATIVE_FLOOR = 0.42    # drop results below this fraction of the top score
