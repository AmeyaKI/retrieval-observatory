# Error Messages Audit (Week 1, Task 1.5)

Triggered each error class and recorded before/after messages.
"Before" = state prior to Week 1 fixes. "After" = current state.

## Summary Table

| Error | Entry Point | Before | After |
|-------|------------|--------|-------|
| Bad YAML | `retobs run` | Raw Python traceback (ScannerError) | Friendly 2-line message with fix hint |
| Bad YAML | `retobs validate` | Raw Python traceback | Friendly 1-line message |
| Missing corpus file | `retobs run` | Validation table with error row | ✅ Already friendly (no change needed) |
| `adapter.hf_biencoder` without `[dense]` | pipeline factory | Error surfaces at query execution time via `error_samples` panel with friendly message | ✅ Now fails fast at pipeline build time with same message |
| `adapter.hf_crossencoder` without `[dense]` | pipeline factory | Same as above | ✅ Now fails fast at pipeline build time |
| `adapter.cohere_rerank` without `[cohere]` | pipeline factory | Fires at rerank time via `error_samples` | ✅ Already has guard in `cohere_adapter.py`; message: "Install with: pip install retobs[cohere]" |
| `adapter.pgvector` without `[pgvector]` | pipeline factory | Fires at retrieve time | ✅ Has guard in `pgvector_adapter.py`; message: "Install with: pip install retobs[pgvector]" |
| `retobs forge run` without `[llm-judge]` | `forge/generation/generator.py` | Fires at first LLM call during run | ✅ Now fails fast at `ForgeGenerator.from_provider()` with message: "Install with: pip install retobs[llm-judge]" |
| `retobs serve` without `[dashboard]` | `retobs serve` | ✅ Already had friendly ImportError catch | ✅ No change needed |
| `retobs classifier train` without `[classifier]` | CLI | ✅ Already had `except ImportError as e: console.print(...)` | ✅ No change needed |
| Missing `GOOGLE_API_KEY` for `forge run` | `forge run` | No error at startup; fails during first LLM call with API error | Unchanged — this is a runtime API key error, not a missing dependency |

## Detailed Before/After Transcripts

### 1. Bad YAML — `retobs run`

**Before:**
```
╭───────────────────── Traceback (most recent call last) ──────────────────────╮
│ /Users/ameyakiwalkar/Documents/retrieval-observatory/retrieval_observatory/c │
│ li.py:34 in run                                                              │
│ ...                                                                          │
╰──────────────────────────────────────────────────────────────────────────────╯
ScannerError: mapping values are not allowed here
  in "/tmp/bad_retobs.yaml", line 1, column 10
```

**After (verified):**
```
Cannot parse config /tmp/bad_retobs.yaml: mapping values are not allowed here
  in "/tmp/bad_retobs.yaml", line 1, column 10
Run retobs validate --config <path> for a detailed config check.
```

### 2. Missing corpus file — `retobs run` (already friendly, no change)

**After (unchanged — already good):**
```
┌─────────┬─────────────────────┬──────────────────────────────┐
│ error   │ custom corpus file  │ custom corpus file does not  │
│         │                     │ exist: /nonexistent/         │
│         │                     │ corpus.jsonl                 │
└─────────┴─────────────────────┴──────────────────────────────┘
```

### 3. `adapter.hf_biencoder` without `[dense]`

**Before (fired at retrieve time, surfaced as error_samples after all queries):**
```
Errors (first unique messages)
• ImportError: HFBiEncoderAdapter requires sentence-transformers and faiss-cpu.
  Install with: pip install retobs[dense]
```
(Appeared only after running all N queries, wasting time)

**After (fails fast at pipeline build time):**
```
ImportError: adapter.hf_biencoder requires sentence-transformers and faiss-cpu.
Install with: pip install retobs[dense]
```
(Raised immediately when building the pipeline, before any queries run)

### 4. `retobs forge run` without `[llm-judge]`

**Before (fired at first `generate()` call, mid-run):**
```
ImportError: GeminiGenerator requires google-generativeai.
Install with: pip install retobs[llm-judge]
```
(Deep in execution, after scan step already ran)

**After (fails fast at `ForgeGenerator.from_provider()`):**
Same message, but raised immediately when the generator is constructed — before any LLM calls or scenario generation begins.

## Changes Made

1. **`retrieval_observatory/cli.py`**: Added `try/except Exception` around `ExperimentConfig.from_yaml()` in both `_run()` and `validate()` functions, replacing raw traceback with a one-line message + hint.

2. **`retrieval_observatory/pipeline/factory.py`**: Added early `try/except ImportError` checks in `_build_hf_biencoder_adapter()` and `_build_hf_crossencoder_adapter()` to fail fast at pipeline build time with the same friendly message that was previously deferred to retrieve time.

3. **`retrieval_observatory/forge/generation/generator.py`**: Added import checks at the start of `_make_generator()` for all three providers (gemini, openai, anthropic), so `ForgeGenerator.from_provider()` now raises `ImportError` with a friendly message immediately.

## Adapters with Already-Good Messages (No Change)

- `cohere_adapter.py` — fires in `rerank()` with: `"Install with: pip install retobs[cohere]"`
- `pgvector_adapter.py` — fires in `retrieve()` with: `"Install with: pip install retobs[pgvector]"`
- `hf_biencoder_adapter.py` — fires in `_build_index()` (now also caught upstream in factory)
- Forge generator classes — fire in `_get_client()` / `generate()` (now also caught upstream in `_make_generator`)
- `retobs serve` — already had `except ImportError: console.print(...)` for dashboard/uvicorn
- `retobs classifier *` — already had `except ImportError: console.print(...)` for scikit-learn
