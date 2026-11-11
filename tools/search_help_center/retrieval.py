"""Real retrieval for search_help_center (bite B5) - chunking, hybrid
search, and checked citations, bare-handed (stdlib only, no framework,
no vector database).

How it works, in the bite's words:

- CHUNKING: each policy document in corpus/ is split into one-idea
  chunks (one per ## section). Every chunk has a stable id -
  "refund-timing/c1" - because an answer cites chunk ids, and a
  citation the checker cannot open is decoration, not proof.

- TWO NETS (hybrid search):
  * the KEYWORD net scores a chunk by the query's exact content words
    it contains, with a heavy bonus for code-like tokens (ORD-88123):
    an identifier has no meaning to match on, only an exact string.
  * the MEANING net turns every chunk into a list of numbers (a
    word-weight vector: term frequency x inverse document frequency)
    and scores by cosine similarity to the query's vector - similar
    word-weights, similar numbers.
  The two scores are normalised and averaged; the top chunks win.

  NAMED GAP (real over toy): a neural embedding model (e.g. Voyage)
  makes its numbers from meaning, so it also catches deep paraphrase
  ("my parcel hasn't shown up" -> the late-package chunk) that counted
  word-weights can miss. The swap point is embed(): replace the
  word-weight vector with a model vector and nothing else changes -
  chunking, both nets, the checker, and the tool contract all stay.

- THE CHECKER: check_claim(claim, chunk_id) is the citation audit.
  Every number in the claim must appear in the cited chunk, and most
  of the claim's content words must be there too. No citation, an
  unknown chunk, a stray number, or unsupported words = FAIL, in
  words the agent can act on. Uncited factual claims fail by design
  (repo rule 1: never invent facts).

The index is rebuilt from the corpus on first use in a process and
written to index.json next to this file, so the artifact the lesson
talks about is a real file a human can open and inspect.
"""

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORPUS_DIR = HERE / "corpus"
INDEX_PATH = HERE / "index.json"

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "for", "is", "are", "was",
    "were", "be", "been", "it", "its", "in", "on", "at", "by", "with",
    "when", "what", "how", "does", "do", "my", "i", "me", "we", "you",
    "your", "our", "their", "this", "that", "if", "may", "can", "will",
    "would", "should", "there", "here", "not", "no", "from", "as",
    "has", "have", "had", "also",
}

# Contraction remnants: "you'll" tokenises to "you" + "ll" - the tail
# carries no fact, and counting it once failed a TRUE claim in the B5
# live run's audit. Remnants are dropped before any scoring.
_REMNANTS = {"ll", "re", "ve"}


def _tokens(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def _stem(word):
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _content_stems(text):
    return [
        _stem(t)
        for t in _tokens(text)
        if t not in STOPWORDS and t not in _REMNANTS and len(t) > 1
    ]


def _codes(text):
    """Code-like tokens (ORD-88123): identifiers the keyword net must
    match exactly, because meaning has nothing to hold on to."""
    return [c.lower() for c in re.findall(r"[A-Za-z]{2,}-\d+", text)]


# --- chunking ---------------------------------------------------------------

def chunk_corpus():
    """Split every corpus document into one-idea chunks. A chunk is one
    ## section; a document with no sections is a single chunk. The
    document title and section name are part of the chunk's searchable
    text (a customer asks about 'late packages', the title's words),
    but the cited text is the section body alone."""
    chunks = []
    for path in sorted(CORPUS_DIR.glob("*.md")):
        doc_id = path.stem
        lines = path.read_text(encoding="utf-8").splitlines()
        title = doc_id
        sections = []
        section, body = "Document", []
        for line in lines:
            if line.startswith("# "):
                title = line[2:].strip()
            elif line.startswith("## "):
                if any(b.strip() for b in body):
                    sections.append((section, " ".join(body).strip()))
                section, body = line[3:].strip(), []
            elif line.strip():
                body.append(line.strip())
        if any(b.strip() for b in body):
            sections.append((section, " ".join(body).strip()))
        for i, (section_name, text) in enumerate(sections, start=1):
            chunks.append(
                {
                    "chunk_id": f"{doc_id}/c{i}",
                    "doc_id": doc_id,
                    "title": title,
                    "section": section_name,
                    "text": text,
                    "searchable": f"{title}. {section_name}. {text}",
                }
            )
    return chunks


# --- the index (both nets' shared ground) ------------------------------------

_index = None


def build_index():
    global _index
    if _index is not None:
        return _index
    chunks = chunk_corpus()
    n = len(chunks)
    doc_freq = Counter()
    chunk_stems = {}
    for chunk in chunks:
        stems = _content_stems(chunk["searchable"])
        chunk_stems[chunk["chunk_id"]] = stems
        for stem in set(stems):
            doc_freq[stem] += 1
    idf = {s: math.log((n + 1) / (df + 1)) + 1.0 for s, df in doc_freq.items()}
    default_idf = math.log(n + 1) + 1.0
    vectors = {}
    for chunk in chunks:
        counts = Counter(chunk_stems[chunk["chunk_id"]])
        total = max(1, sum(counts.values()))
        vectors[chunk["chunk_id"]] = {
            s: (c / total) * idf[s] for s, c in counts.items()
        }
    _index = {
        "chunks": chunks,
        "chunk_stems": chunk_stems,
        "idf": idf,
        "default_idf": default_idf,
        "vectors": vectors,
    }
    fingerprint = hashlib.sha256(
        "".join(c["searchable"] for c in chunks).encode("utf-8")
    ).hexdigest()[:12]
    INDEX_PATH.write_text(
        json.dumps(
            {
                "fingerprint": fingerprint,
                "chunks": [
                    {k: c[k] for k in ("chunk_id", "doc_id", "title", "section", "text")}
                    for c in chunks
                ],
                "idf": idf,
                "vectors": vectors,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return _index


def get_chunk(chunk_id):
    index = build_index()
    for chunk in index["chunks"]:
        if chunk["chunk_id"] == chunk_id:
            return chunk
    return None


# --- the meaning net ----------------------------------------------------------

def embed(text):
    """Text -> a list of numbers (here, a term -> weight mapping).
    THE SWAP POINT: a model embedding (e.g. Voyage) replaces this
    function and returns a dense vector instead; search() then compares
    vectors the same way. Nothing else in this file changes."""
    index = build_index()
    counts = Counter(_content_stems(text))
    total = max(1, sum(counts.values()))
    return {
        s: (c / total) * index["idf"].get(s, index["default_idf"])
        for s, c in counts.items()
    }


def _cosine(a, b):
    dot = sum(w * b.get(s, 0.0) for s, w in a.items())
    norm_a = math.sqrt(sum(w * w for w in a.values()))
    norm_b = math.sqrt(sum(w * w for w in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# --- hybrid search --------------------------------------------------------------

def search(query, top_k=3):
    index = build_index()
    query_stems = set(_content_stems(query))
    query_codes = _codes(query)
    query_vector = embed(query)
    scored = []
    for chunk in index["chunks"]:
        stems = set(index["chunk_stems"][chunk["chunk_id"]])
        keyword = len(query_stems & stems)
        for code in query_codes:
            if code in chunk["searchable"].lower():
                keyword += 3
        meaning = _cosine(query_vector, index["vectors"][chunk["chunk_id"]])
        scored.append((keyword, meaning, chunk))
    max_keyword = max(1, max(k for k, _, _ in scored))
    results = []
    for keyword, meaning, chunk in scored:
        combined = 0.5 * (keyword / max_keyword) + 0.5 * meaning
        if combined < 0.12 or (keyword == 0 and meaning < 0.05):
            continue
        matched_by = []
        if keyword:
            matched_by.append("keyword")
        if meaning >= 0.05:
            matched_by.append("meaning")
        results.append(
            {
                "chunk_id": chunk["chunk_id"],
                "title": chunk["title"],
                "section": chunk["section"],
                "text": chunk["text"],
                "score": round(combined, 3),
                "matched_by": matched_by,
            }
        )
    results.sort(key=lambda r: -r["score"])
    return results[:top_k]


# --- the citation checker -------------------------------------------------------

def check_claim(claim, chunk_id=None):
    """Audit one factual claim against the chunk it cites. Returns a
    dict with ok=True/False and a message written for the agent (and
    the human) to act on - the B4 lesson in new clothes: a citation is
    a pointer, and proof is the read-back of the chunk itself."""
    if not chunk_id:
        return {
            "ok": False,
            "message": (
                "FAIL: no citation. A factual claim must name the chunk it "
                "came from (e.g. 'refund-timing/c1') - an uncited claim is "
                "an invented one until it cites."
            ),
        }
    chunk = get_chunk(chunk_id)
    if chunk is None:
        return {
            "ok": False,
            "message": f"FAIL: '{chunk_id}' is not a chunk in the corpus - the citation points at nothing.",
        }
    claim_numbers = set(re.findall(r"\d+", claim))
    chunk_numbers = set(re.findall(r"\d+", chunk["searchable"]))
    stray = sorted(claim_numbers - chunk_numbers)
    if stray:
        return {
            "ok": False,
            "message": (
                f"FAIL: the claim mentions {', '.join(stray)}, which does "
                f"not appear in {chunk_id} (\"{chunk['text']}\"). A number "
                "the chunk does not contain is an invented number."
            ),
        }
    claim_stems = set(_content_stems(claim)) - set(re.findall(r"\d+", claim))
    chunk_stem_set = set(_content_stems(chunk["searchable"]))
    if claim_stems:
        present = claim_stems & chunk_stem_set
        if len(present) / len(claim_stems) < 0.6:
            missing = sorted(claim_stems - chunk_stem_set)
            return {
                "ok": False,
                "message": (
                    f"FAIL: the claim's words {', '.join(missing[:4])} are "
                    f"not in {chunk_id} - the chunk does not support this "
                    "claim as written."
                ),
            }
    return {
        "ok": True,
        "message": (
            f"PASS: every number and key word in the claim appears in "
            f"{chunk_id}. The citation checks out."
        ),
    }
