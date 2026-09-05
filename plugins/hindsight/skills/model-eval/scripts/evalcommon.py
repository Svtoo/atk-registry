"""Shared plumbing for the hindsight-eval harnesses (stdlib only).

Both judge.py (Tier 2) and retrieval_test.py (Tier 3) need the same four
things, so they live here rather than being copy-pasted:

  * corpus loading and the ground-truth record for one memory
  * loading whatever the Tier-1 extraction run wrote, normalised to
    {memory_id: {arm: [fact_text, ...]}}
  * a JSON-over-HTTP client with retries, built on urllib
  * verbatim token matching, atomic JSON writes, stderr progress

Nothing here talks to a specific service. Service-specific request shapes
live in the harness that owns them.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, NoReturn, Sequence

# --------------------------------------------------------------------------
# paths
# --------------------------------------------------------------------------

HARNESS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(HARNESS_DIR)
CORPUS_DIR = os.path.join(ROOT_DIR, "corpus")
# The plugin is found through ATK's home, never by walking out of this skill;
# model-eval.sh exports the variable so every step of a run agrees on it.
PLUGIN_DIR = os.environ.get("HINDSIGHT_PLUGIN_DIR") or os.path.join(
    os.environ.get("ATK_HOME") or os.path.expanduser("~/.atk"), "plugins", "hindsight")


def retain_instructions() -> str:
    """The retain instructions conform applies: custom/ wins over the shipped file."""
    for path in (os.path.join(PLUGIN_DIR, "custom", "retain-instructions.md"),
                 os.path.join(PLUGIN_DIR, "retain-instructions.md")):
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                text = fh.read().strip()
            if text:
                return text
    die(f"no retain instructions under {PLUGIN_DIR}",
        "the arms must extract against the instructions production uses")

STRATA = ("code_handover", "decisions_rationale", "meetings_people", "short_factual")


class EvalError(Exception):
    """Anything the harness refuses to guess its way past."""


def die(msg: str, hint: str | None = None) -> NoReturn:
    print(f"error: {msg}", file=sys.stderr)
    if hint:
        print(f"       {hint}", file=sys.stderr)
    raise SystemExit(2)


# --------------------------------------------------------------------------
# corpus
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Memory:
    """One corpus memory plus its ground truth."""

    id: str
    stratum: str
    text: str
    hard_tokens: tuple[str, ...]
    expected_min_facts: int
    traps: tuple[str, ...]


def load_corpus(corpus_dir: str = CORPUS_DIR, strata: Sequence[str] | None = None,
                subset_file: str | None = None) -> dict[str, Memory]:
    """Read corpus/*.json into {memory_id: Memory}, ordered by file then index.

    Raises EvalError on a malformed or missing corpus rather than returning a
    partial one: every downstream metric is defined against this ground truth.
    """
    if not os.path.isdir(corpus_dir):
        raise EvalError(f"corpus directory not found: {corpus_dir}")
    wanted = set(strata) if strata else None
    # The arms were loaded with a 52-memory subset. A query set built from all
    # 100 would target memories no bank was ever given, scoring them as
    # retrieval misses for every arm and halving the result.
    keep = None
    if subset_file:
        with open(subset_file, encoding="utf-8") as fh:
            keep = {line.strip() for line in fh if line.strip()}
    out: dict[str, Memory] = {}
    files = sorted(f for f in os.listdir(corpus_dir)
                   if f.endswith(".json") and f != "queries.json")
    if not files:
        raise EvalError(f"no .json files in {corpus_dir}")
    for fname in files:
        path = os.path.join(corpus_dir, fname)
        with open(path, encoding="utf-8") as fh:
            try:
                doc = json.load(fh)
            except json.JSONDecodeError as exc:
                raise EvalError(f"{path} is not valid JSON: {exc}") from exc
        if not isinstance(doc, dict) or "memories" not in doc:
            raise EvalError(f"{path}: expected an object with a 'memories' key")
        stratum = doc.get("stratum") or os.path.splitext(fname)[0]
        if wanted is not None and stratum not in wanted:
            continue
        for idx, raw in enumerate(doc["memories"]):
            if keep is not None and raw.get("id") not in keep:
                continue
            for required in ("id", "text"):
                if required not in raw:
                    raise EvalError(f"{path}: memory #{idx} has no '{required}'")
            mem = Memory(
                id=raw["id"],
                stratum=raw.get("stratum", stratum),
                text=raw["text"],
                hard_tokens=tuple(raw.get("hard_tokens") or ()),
                expected_min_facts=int(raw.get("expected_min_facts") or 0),
                traps=tuple(raw.get("traps") or ()),
            )
            if mem.id in out:
                raise EvalError(f"duplicate memory id {mem.id!r} (second copy in {path})")
            out[mem.id] = mem
    if not out:
        raise EvalError(f"no memories loaded from {corpus_dir} (strata filter: {strata})")
    return out


# --------------------------------------------------------------------------
# extractions produced by the Tier-1 run
# --------------------------------------------------------------------------

# Canonical shape written by the extraction runner and read here:
#
# {
#   "run_id": "2026-08-24T12:00:00Z",
#   "arms": [{"arm": "deepseek-v4-pro", "model": "deepseek-v4-pro", "bank": "eval-deepseek-v4-pro"}],
#   "extractions": [
#     {"memory_id": "code_handover-001", "arm": "deepseek-v4-pro",
#      "facts": [{"text": "..."}, ...], "error": null}
#   ]
# }
#
# Tolerated variants are handled in _coerce_* below; anything else is an error,
# never a silent empty result.

_ARM_KEYS = ("arm", "arm_id", "model", "model_id", "name")
_MEM_KEYS = ("memory_id", "memory", "id", "source_id", "corpus_id")
_FACT_LIST_KEYS = ("facts", "memories", "extracted_facts", "items", "results")
_FACT_TEXT_KEYS = ("text", "fact", "content", "memory", "body")


@dataclass
class ExtractionSet:
    arms: list[str]
    by_memory: dict[str, dict[str, list[str]]]
    arm_meta: dict[str, dict[str, Any]] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    source_path: str = ""
    # arm -> memory ids that arm demonstrably ingested. A memory absent from an
    # arm's set is one whose retain never landed, which is a different fact
    # from "ingested and extracted nothing" and must not be scored as one.
    ingested: dict[str, set[str]] = field(default_factory=dict)

    def facts(self, memory_id: str, arm: str) -> list[str]:
        return self.by_memory.get(memory_id, {}).get(arm, [])

    def total_facts(self) -> int:
        return sum(len(f) for per_arm in self.by_memory.values() for f in per_arm.values())

    def was_ingested(self, memory_id: str, arm: str) -> bool:
        """True when this arm is known to have ingested this memory."""
        return memory_id in self.ingested.get(arm, set())

    def arms_for(self, memory_id: str) -> list[str]:
        """Arms that ingested this memory, in the set's arm order."""
        return [arm for arm in self.arms if self.was_ingested(memory_id, arm)]

    def memory_ids(self) -> list[str]:
        """Every memory some arm ingested or produced a fact for.

        A memory every arm ingested and every arm extracted nothing from is a
        real result, so it is listed even though it carries no facts.
        """
        seen: list[str] = list(self.by_memory)
        known = set(seen)
        for arm in self.arms:
            for mem_id in sorted(self.ingested.get(arm, set())):
                if mem_id not in known:
                    known.add(mem_id)
                    seen.append(mem_id)
        return seen

    def total_ingested(self) -> int:
        return sum(len(v) for v in self.ingested.values())


def _coerce_fact_text(raw: Any, where: str) -> str:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        for key in _FACT_TEXT_KEYS:
            val = raw.get(key)
            if isinstance(val, str) and val.strip():
                return val
        raise EvalError(f"{where}: fact object has none of {_FACT_TEXT_KEYS}: {sorted(raw)}")
    raise EvalError(f"{where}: fact is {type(raw).__name__}, expected str or object")


def _first_key(obj: dict[str, Any], keys: Iterable[str]) -> str | None:
    for key in keys:
        val = obj.get(key)
        if isinstance(val, str) and val:
            return val
    return None


def load_extractions(path: str) -> ExtractionSet:
    """Load the Tier-1 output and normalise it to {memory: {arm: [fact_text]}}."""
    if not os.path.exists(path):
        raise EvalError(
            f"extractions file not found: {path}\n"
            "       Tier 2 and Tier 3 both score what Tier 1 extracted; run the "
            "extraction pass first, or point --extractions at its output."
        )
    with open(path, encoding="utf-8") as fh:
        try:
            doc = json.load(fh)
        except json.JSONDecodeError as exc:
            raise EvalError(f"{path} is not valid JSON: {exc}") from exc

    by_memory: dict[str, dict[str, list[str]]] = {}
    arm_meta: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    arms_order: list[str] = []
    # A record in this file - even one with an empty fact list or an error - is
    # evidence the arm was asked about that memory. No record at all is not.
    ingested: dict[str, set[str]] = {}

    def note_arm(arm: str) -> None:
        if arm not in arms_order:
            arms_order.append(arm)

    if isinstance(doc, dict):
        for entry in doc.get("arms") or []:
            if isinstance(entry, str):
                note_arm(entry)
                arm_meta.setdefault(entry, {})
            elif isinstance(entry, dict):
                arm = _first_key(entry, _ARM_KEYS)
                if arm:
                    note_arm(arm)
                    arm_meta[arm] = dict(entry)

    records: list[dict[str, Any]] | None = None
    if isinstance(doc, list):
        records = doc
    elif isinstance(doc, dict):
        for key in ("extractions", "records", "runs", "results"):
            val = doc.get(key)
            if isinstance(val, list):
                records = val
                break
        if records is None and isinstance(doc.get("by_arm"), dict):
            # {"by_arm": {"arm": {"memory_id": [facts]}}}
            for arm, per_mem in doc["by_arm"].items():
                note_arm(arm)
                if not isinstance(per_mem, dict):
                    raise EvalError(f"{path}: by_arm[{arm!r}] must be an object of memory_id -> facts")
                for mem_id, facts in per_mem.items():
                    texts = [
                        _coerce_fact_text(f, f"{path}: by_arm[{arm!r}][{mem_id!r}]")
                        for f in (facts or [])
                    ]
                    by_memory.setdefault(mem_id, {})[arm] = texts
                    ingested.setdefault(arm, set()).add(mem_id)
            records = []

    if records is None:
        raise EvalError(
            f"{path}: cannot find the extraction records. Expected a top-level list, "
            "or an object with 'extractions' (list) or 'by_arm' (object). "
            f"Saw keys: {sorted(doc) if isinstance(doc, dict) else type(doc).__name__}"
        )

    for idx, rec in enumerate(records):
        where = f"{path}: record #{idx}"
        if not isinstance(rec, dict):
            raise EvalError(f"{where}: expected an object, got {type(rec).__name__}")
        arm = _first_key(rec, _ARM_KEYS)
        mem_id = _first_key(rec, _MEM_KEYS)
        if not arm:
            raise EvalError(f"{where}: no arm name (looked for {_ARM_KEYS})")
        if not mem_id:
            raise EvalError(f"{where}: no memory id (looked for {_MEM_KEYS})")
        note_arm(arm)
        raw_facts = None
        for key in _FACT_LIST_KEYS:
            if isinstance(rec.get(key), list):
                raw_facts = rec[key]
                break
        if raw_facts is None:
            if rec.get("error"):
                raw_facts = []
            else:
                raise EvalError(f"{where}: no fact list (looked for {_FACT_LIST_KEYS})")
        texts = [_coerce_fact_text(f, where) for f in raw_facts]
        slot = by_memory.setdefault(mem_id, {})
        if arm in slot:
            raise EvalError(f"{where}: duplicate ({mem_id!r}, {arm!r}) pair")
        slot[arm] = texts
        ingested.setdefault(arm, set()).add(mem_id)
        if rec.get("error"):
            errors.append({"memory_id": mem_id, "arm": arm, "error": rec["error"]})

    result = ExtractionSet(
        arms=arms_order,
        by_memory=by_memory,
        arm_meta=arm_meta,
        errors=errors,
        source_path=path,
        ingested=ingested,
    )
    if not result.arms:
        raise EvalError(f"{path}: no arms found")
    if result.total_facts() == 0:
        raise EvalError(
            f"{path}: parsed {len(by_memory)} memories across {len(result.arms)} arms but "
            "zero facts. Either the extraction run produced nothing, or this file's "
            "shape is not the one documented in evalcommon.load_extractions."
        )
    return result


# --------------------------------------------------------------------------
# verbatim matching
# --------------------------------------------------------------------------

_WS = re.compile(r"\s+")


def norm_ws(text: str) -> str:
    """Collapse whitespace runs; keep case and punctuation."""
    return _WS.sub(" ", text).strip()


def strip_code_fence(token: str) -> str:
    return norm_ws(token).strip("`").strip()


def verbatim_contains(haystack: str, token: str) -> bool:
    """True when `token` survives inside `haystack` character-for-character.

    Whitespace runs are normalised on both sides (a wrapped line is still
    verbatim); case and punctuation are not touched, because the contract is
    about identifiers surviving exactly as written.
    """
    tok = strip_code_fence(token)
    if not tok:
        return False
    return tok in norm_ws(haystack)


_LOOSE = re.compile(r"[^0-9a-z]+")


def loose_contains(haystack: str, token: str) -> bool:
    """Diagnostic-only match: case-folded, punctuation-stripped."""
    tok = _LOOSE.sub("", strip_code_fence(token).lower())
    if not tok:
        return False
    return tok in _LOOSE.sub("", haystack.lower())


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


class HttpError(EvalError):
    def __init__(self, status: int, url: str, body: str):
        super().__init__(f"HTTP {status} from {url}: {body[:500]}")
        self.status = status
        self.url = url
        self.body = body


RETRY_STATUSES = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 529})


def http_json(
    url: str,
    method: str = "GET",
    body: Any = None,
    headers: dict[str, str] | None = None,
    timeout: float = 120.0,
    retries: int = 4,
    backoff: float = 1.5,
    rng: random.Random | None = None,
    on_retry: Callable[[int, str], None] | None = None,
) -> Any:
    """One JSON request with bounded retries. Returns the decoded body.

    Retries connection errors and RETRY_STATUSES, honouring Retry-After.
    Any other status raises HttpError immediately: no silent empty result.
    """
    payload = None if body is None else json.dumps(body).encode("utf-8")
    hdrs = {"Accept": "application/json"}
    if payload is not None:
        hdrs["Content-Type"] = "application/json"
    hdrs.update(headers or {})
    rng = rng or random.Random(0)
    last: Exception | None = None

    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=payload, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else None
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")
            except Exception:  # noqa: BLE001 - the body is best-effort context
                pass
            if exc.code not in RETRY_STATUSES or attempt == retries:
                raise HttpError(exc.code, url, detail) from exc
            last = exc
            delay = _retry_after(exc.headers.get("Retry-After")) or backoff**attempt
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            if attempt == retries:
                raise EvalError(f"{method} {url} failed after {retries + 1} tries: {exc}") from exc
            last = exc
            delay = backoff**attempt
        delay += rng.random() * 0.25
        if on_retry:
            on_retry(attempt + 1, f"{type(last).__name__}: {last}")
        time.sleep(delay)
    raise EvalError(f"{method} {url} exhausted retries: {last}")


def _retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------


def write_json_atomic(path: str, obj: Any) -> str:
    """Write pretty JSON via a temp file + rename, so a crash never truncates."""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False, sort_keys=False)
        fh.write("\n")
    os.replace(tmp, path)
    return path


def mean(values: Sequence[float]) -> float | None:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def median(values: Sequence[float]) -> float | None:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    if len(vals) % 2:
        return round(float(vals[mid]), 4)
    return round((vals[mid - 1] + vals[mid]) / 2, 4)


class Progress:
    """Thread-safe one-line progress on stderr; silent when not a tty."""

    def __init__(self, total: int, label: str, enabled: bool = True):
        self.total = total
        self.label = label
        self.done = 0
        self.enabled = enabled and total > 0
        self._lock = threading.Lock()
        self._started = time.time()

    def tick(self, note: str = "") -> None:
        with self._lock:
            self.done += 1
            if not self.enabled:
                return
            elapsed = time.time() - self._started
            rate = self.done / elapsed if elapsed > 0 else 0.0
            line = f"\r{self.label}: {self.done}/{self.total} ({rate:.1f}/s) {note[:60]:<60}"
            sys.stderr.write(line)
            sys.stderr.flush()

    def close(self) -> None:
        if self.enabled:
            sys.stderr.write("\n")
            sys.stderr.flush()


# --------------------------------------------------------------------------
# hindsight
# --------------------------------------------------------------------------

DEFAULT_BANK_TEMPLATE = "eval-{arm}"


class Hindsight:
    """Client for the Hindsight HTTP API (v0.9.x).

      GET  {base}/health
      GET  {base}/v1/{tenant}/banks
      GET  {base}/v1/{tenant}/banks/{bank}/documents?limit&offset
      GET  {base}/v1/{tenant}/banks/{bank}/memories/list?limit&offset
      POST {base}/v1/{tenant}/banks/{bank}/memories/recall

    Shared by Tier 2 (reading a bank's facts) and Tier 3 (recall), so the
    request shapes are defined exactly once.
    """

    def __init__(self, base_url: str, tenant: str = "default", api_key: str | None = None,
                 timeout: float = 120.0, retries: int = 3, page_size: int = 200):
        self.base = base_url.rstrip("/")
        self.tenant = tenant
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.timeout = timeout
        self.retries = retries
        self.page_size = page_size

    def _bank(self, bank: str, suffix: str = "") -> str:
        return f"{self.base}/v1/{self.tenant}/banks/{bank}{suffix}"

    def bank_url(self, bank: str, suffix: str = "") -> str:
        """The URL this client would call, for error messages and provenance."""
        return self._bank(bank, suffix)

    def health(self) -> dict[str, Any]:
        try:
            http_json(f"{self.base}/health", timeout=15, retries=1, headers=self.headers)
        except EvalError as exc:
            raise EvalError(
                f"cannot reach Hindsight at {self.base}: {exc}\n"
                "       Is the eval instance running on that port? "
                "(harness/run_arm.sh brings it up; it maps host 18888 -> container 8888)"
            ) from exc
        info: dict[str, Any] = {"health": "ok"}
        try:
            info["version"] = http_json(f"{self.base}/version", timeout=15, retries=1,
                                        headers=self.headers)
        except EvalError:
            info["version"] = None
        return info

    def banks(self) -> list[str]:
        doc = http_json(f"{self.base}/v1/{self.tenant}/banks", timeout=30,
                        retries=self.retries, headers=self.headers)
        entries = doc.get("banks", doc.get("items")) if isinstance(doc, dict) else doc
        if not isinstance(entries, list):
            raise EvalError(f"unexpected /v1/{self.tenant}/banks response: {json.dumps(doc)[:300]}")
        out = []
        for entry in entries:
            if isinstance(entry, dict):
                name = entry.get("bank_id") or entry.get("id") or entry.get("name")
                if name:
                    out.append(name)
            elif isinstance(entry, str):
                out.append(entry)
        return out

    _PAGE_LIST_KEYS = ("items", "memories", "results", "units", "memory_units", "documents")

    def _paginate(self, bank: str, suffix: str, max_pages: int = 500) -> list[dict[str, Any]]:
        """Every row behind one paginated bank endpoint.

        A shape it does not recognise, a server ignoring limit/offset, or a
        listing longer than max_pages all raise: a short list returned as if it
        were complete would silently mislabel every downstream result.
        """
        rows: list[dict[str, Any]] = []
        offset = 0
        total: int | None = None
        prev_page_ids: tuple[Any, ...] | None = None
        for _ in range(max_pages):
            url = f"{self._bank(bank, suffix)}?limit={self.page_size}&offset={offset}"
            doc = http_json(url, timeout=self.timeout, retries=self.retries,
                            headers=self.headers)
            page = None
            if isinstance(doc, dict):
                for key in self._PAGE_LIST_KEYS:
                    if isinstance(doc.get(key), list):
                        page = doc[key]
                        break
                if total is None:
                    total = doc.get("total")
            elif isinstance(doc, list):
                page = doc
            if page is None:
                raise EvalError(
                    f"{url} returned no list of rows "
                    f"(keys: {sorted(doc) if isinstance(doc, dict) else type(doc).__name__})"
                )
            page_ids = tuple(f.get("id") for f in page if isinstance(f, dict))
            if page and page_ids == prev_page_ids:
                # The server handed back the same page for a higher offset: it
                # is ignoring pagination, and continuing would inflate the
                # listing with duplicates.
                raise EvalError(f"{url} ignored limit/offset (identical page repeated)")
            prev_page_ids = page_ids
            rows.extend(f for f in page if isinstance(f, dict))
            offset += len(page)
            if not page or (total is not None and offset >= int(total)):
                return rows
            if len(page) < self.page_size and total is None:
                return rows
        raise EvalError(
            f"{self._bank(bank, suffix)} still had rows after {max_pages} pages "
            f"({len(rows)} read); raise max_pages rather than scoring a partial listing"
        )

    def list_facts(self, bank: str, max_pages: int = 500) -> tuple[list[dict[str, Any]], str]:
        """Every fact in a bank, paginated. Returns (facts, endpoint_used).

        Tries /memories/list first (what the Tier-1 scorer uses) and falls back
        to /memories. A shape it does not recognise raises rather than returning
        a short list: a truncated inventory would silently mislabel results.
        """
        last_error = None
        for suffix in ("/memories/list", "/memories"):
            try:
                facts = self._paginate(bank, suffix, max_pages)
            except (EvalError, HttpError) as exc:
                last_error = exc
                continue
            return facts, f"GET {self._bank(bank, suffix)} ({len(facts)} facts)"
        raise EvalError(f"cannot list facts in bank {bank!r}: {last_error}")

    def list_documents(self, bank: str, max_pages: int = 500) -> tuple[list[dict[str, Any]], str]:
        """Every source document in a bank. Returns (documents, endpoint_used).

        This is the only evidence that a retain landed at all: a document with
        no facts is an extractor that produced nothing, while no document is a
        write that never happened. Raises if the endpoint cannot be read - the
        caller must decide what to do about it, not guess.
        """
        docs = self._paginate(bank, "/documents", max_pages)
        return docs, f"GET {self._bank(bank, '/documents')} ({len(docs)} documents)"

    def recall(self, bank: str, query: str, budget: str = "mid", max_tokens: int = 4096,
               types: list[str] | None = None, tags: list[str] | None = None,
               tags_match: str = "any", rng: random.Random | None = None
               ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        body: dict[str, Any] = {"query": query, "budget": budget, "max_tokens": max_tokens}
        if types:
            body["types"] = types
        if tags:
            body["tags"] = tags
            body["tags_match"] = tags_match
        url = self._bank(bank, "/memories/recall")
        started = time.time()
        doc = http_json(url, method="POST", body=body, headers=self.headers,
                        timeout=self.timeout, retries=self.retries, rng=rng)
        meta = {"latency_s": round(time.time() - started, 3)}
        results = None
        if isinstance(doc, dict):
            for key in ("results", "memories", "items", "facts"):
                if isinstance(doc.get(key), list):
                    results = doc[key]
                    break
            meta["total_available"] = doc.get("total") or doc.get("total_results")
        if results is None:
            raise EvalError(
                f"recall response from {url} has no results list "
                f"(keys: {sorted(doc) if isinstance(doc, dict) else type(doc).__name__})"
            )
        return results, meta


def fact_text(fact: Any) -> str:
    """The scoreable body of a bank fact. 'context' is a header, not the fact."""
    if isinstance(fact, str):
        return fact
    if isinstance(fact, dict):
        for key in ("text", "content", "fact", "summary"):
            val = fact.get(key)
            if isinstance(val, str) and val.strip():
                return val
    return ""


# --------------------------------------------------------------------------
# document provenance
# --------------------------------------------------------------------------

# Where a document can carry the corpus memory id it was built from. Tier-1
# posts document_id=<corpus memory id>, but Hindsight is free to assign its own
# id instead, so these are tried in order before a document is called unknown.
DOC_META_KEYS = ("eval_memory_id", "memory_id", "corpus_id", "source_memory_id")


@dataclass
class DocumentIndex:
    """Hindsight document id -> corpus memory id, and how each was resolved."""

    bank: str
    by_document: dict[str, str] = field(default_factory=dict)
    strategies: dict[str, str] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)
    endpoint: str = ""
    available: bool = False
    error: str | None = None
    valid_ids: frozenset[str] = frozenset()

    def resolve(self, doc_id: Any) -> str | None:
        """The corpus memory a fact came from, or None when it cannot be told."""
        if not isinstance(doc_id, str) or not doc_id:
            return None
        hit = self.by_document.get(doc_id)
        if hit:
            return hit
        # Tier-1 writes the corpus id as the document id, which stays usable
        # even when the documents endpoint itself could not be read.
        return doc_id if doc_id in self.valid_ids else None

    def memory_ids(self) -> set[str]:
        return set(self.by_document.values())

    def describe(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for strategy in self.strategies.values():
            counts[strategy] = counts.get(strategy, 0) + 1
        return {
            "endpoint": self.endpoint,
            "available": self.available,
            "documents_resolved": len(self.by_document),
            "resolved_by": counts,
            "unresolved_document_ids": self.unresolved[:50],
            "unresolved_total": len(self.unresolved),
            "error": self.error,
        }


def build_document_index(hs: "Hindsight", bank: str, memories: dict[str, Memory],
                         max_pages: int = 500) -> DocumentIndex:
    """Read a bank's documents and link each one back to a corpus memory.

    Never raises: an unreadable endpoint is reported as available=False with the
    error attached, because only the caller knows whether it can proceed without
    provenance. Documents that link to nothing are listed, never dropped.
    """
    if not isinstance(memories, dict):
        raise EvalError(
            "build_document_index needs {memory_id: Memory}, "
            f"got {type(memories).__name__}"
        )
    valid_ids = frozenset(memories)
    by_hash: dict[str, str] = {}
    by_text: dict[str, str] = {}
    for mem_id, mem in memories.items():
        text = getattr(mem, "text", None)
        if isinstance(text, str):
            by_hash.setdefault(hashlib.sha256(text.encode("utf-8")).hexdigest(), mem_id)
            by_text.setdefault(text, mem_id)

    index = DocumentIndex(bank=bank, valid_ids=valid_ids,
                          endpoint=f"GET {hs.bank_url(bank, '/documents')}")
    try:
        documents, note = hs.list_documents(bank, max_pages)
    except (EvalError, HttpError) as exc:
        index.error = str(exc)
        return index
    index.available = True
    index.endpoint = note

    for doc in documents:
        doc_id = doc.get("id") or doc.get("document_id")
        if doc_id is None:
            index.unresolved.append("(document with no id)")
            continue
        doc_id = str(doc_id)
        hit = None
        strategy = ""
        for container in ("document_metadata", "metadata"):
            meta = doc.get(container)
            if isinstance(meta, dict):
                for key in DOC_META_KEYS:
                    val = meta.get(key)
                    if isinstance(val, str) and val in valid_ids:
                        hit, strategy = val, container
                        break
            if hit:
                break
        if not hit and doc_id in valid_ids:
            hit, strategy = doc_id, "document_id_literal"
        if not hit:
            chash = doc.get("content_hash")
            if isinstance(chash, str) and chash in by_hash:
                hit, strategy = by_hash[chash], "content_hash"
        if not hit:
            original = doc.get("original_text")
            if isinstance(original, str) and original in by_text:
                hit, strategy = by_text[original], "original_text"
        if not hit:
            index.unresolved.append(doc_id)
            continue
        index.by_document[doc_id] = hit
        index.strategies[doc_id] = strategy
    return index


def resolve_banks(arms: list[str], extractions: ExtractionSet | None,
                  bank_template: str | None, arm_bank_pairs: list[str] | None) -> dict[str, str]:
    """Arm -> bank name.

    Precedence, most explicit first: --arm-bank, an explicitly passed
    --bank-template, the bank recorded by the Tier-1 run, then eval-<arm>.
    A flag the operator typed must never lose to file metadata, or a typo'd
    template silently tests the wrong banks.
    """
    banks: dict[str, str] = {}
    for arm in arms:
        meta = (extractions.arm_meta.get(arm, {}) if extractions else {})
        if bank_template:
            banks[arm] = bank_template.format(arm=arm)
        elif isinstance(meta.get("bank"), str) and meta["bank"]:
            banks[arm] = meta["bank"]
        else:
            banks[arm] = DEFAULT_BANK_TEMPLATE.format(arm=arm)
    for pair in arm_bank_pairs or []:
        if "=" not in pair:
            die(f"--arm-bank expects arm=bank, got {pair!r}")
        arm, bank = pair.split("=", 1)
        if arm not in banks:
            die(f"--arm-bank names unknown arm {arm!r}", f"known arms: {', '.join(arms)}")
        banks[arm] = bank
    return banks


def facts_from_banks(hs: Hindsight, banks: dict[str, str],
                     memories: dict[str, Memory],
                     max_pages: int = 500) -> tuple[ExtractionSet, dict[str, Any]]:
    """Build an ExtractionSet from live banks, grouping facts by document.

    Tier-1 retains each corpus memory with document_id set to the corpus memory
    id, so the document is the join key back to ground truth. Facts that link to
    no known memory are reported, never silently dropped.

    The bank's document list also supplies `ingested`: which memories actually
    reached each arm. Without it a retain that never landed is indistinguishable
    from an extractor that returned nothing, and the judge scores the first as
    if it were the second - grading a model on text it was never shown.
    """
    if not isinstance(memories, dict):
        raise EvalError(
            f"facts_from_banks needs {{memory_id: Memory}}, got {type(memories).__name__}"
        )
    by_memory: dict[str, dict[str, list[str]]] = {}
    ingested: dict[str, set[str]] = {}
    notes: dict[str, Any] = {}
    unmatched: list[dict[str, Any]] = []
    for arm, bank in banks.items():
        index = build_document_index(hs, bank, memories, max_pages)
        if not index.available:
            raise EvalError(
                f"cannot read the document list for arm {arm!r} (bank {bank!r}): "
                f"{index.error}\n"
                "       Without it, a memory the retain never reached looks exactly "
                "like one the model extracted nothing from, and the judge would "
                "score the first as a model failure. Fix the endpoint, or judge a "
                "Tier-1 extractions file instead (--facts-from extractions)."
            )
        arm_ingested = index.memory_ids()
        facts, fact_note = hs.list_facts(bank, max_pages)
        empty_text = 0
        kept = 0
        for fact in facts:
            doc_id = fact.get("document_id") or fact.get("source_id")
            mem_id = index.resolve(doc_id)
            if mem_id is None:
                unmatched.append({"arm": arm, "document_id": doc_id, "fact_id": fact.get("id")})
                continue
            text = fact_text(fact)
            if not text:
                empty_text += 1
                continue
            by_memory.setdefault(mem_id, {}).setdefault(arm, []).append(text)
            arm_ingested.add(mem_id)  # a linked fact is proof its document landed
            kept += 1
        ingested[arm] = arm_ingested
        with_facts = {m for m in arm_ingested if by_memory.get(m, {}).get(arm)}
        notes[arm] = {
            "facts": fact_note,
            "facts_kept": kept,
            "facts_with_empty_text": empty_text,
            "documents": index.describe(),
            "memories_ingested": len(arm_ingested),
            "memories_ingested_without_facts": sorted(arm_ingested - with_facts),
            "memories_never_ingested": sorted(set(memories) - arm_ingested),
        }
    result = ExtractionSet(
        arms=list(banks),
        by_memory=by_memory,
        arm_meta={arm: {"bank": bank} for arm, bank in banks.items()},
        errors=[{"unmatched_document_ids": unmatched[:50], "unmatched_total": len(unmatched)}]
        if unmatched else [],
        source_path="hindsight-banks",
        ingested=ingested,
    )
    if result.total_ingested() == 0:
        raise EvalError(
            "no corpus memory was ingested by any bank "
            f"({', '.join(f'{a}->{b}' for a, b in banks.items())}). "
            "Has the retain pass run against this instance?"
        )
    if result.total_facts() == 0:
        raise EvalError(
            "no facts found in any bank "
            f"({', '.join(f'{a}->{b}' for a, b in banks.items())}), "
            f"though {result.total_ingested()} arm/memory pairs were ingested. "
            "Every arm extracting nothing from every memory is a stack failure, "
            "not a result: check the retain pass before judging."
        )
    return result, notes
