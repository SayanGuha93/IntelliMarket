# IntelliMarket RAG catalog

The module provides a standalone, read-only query interface over a generated SQLite
catalog. Its inputs are the original `data/flipkart.csv` and `data/myntra.csv`.
The CSVs are ignored by the parent repository. Place copies of the original
datasets at those paths on a fresh checkout.

## Windows setup and usage

From the repository root, enter the module and use Python 3.11 or newer with
SQLite FTS5. This phase uses only the Python standard library.

```powershell
Set-Location rag_chatbot
py -3.12 -m venv --without-pip .venv
./.venv/Scripts/python.exe -B -m intellimarket_rag build
./.venv/Scripts/python.exe -B -m unittest discover -s tests -v
```

If the Windows launcher is unavailable, run the equivalent `-m venv` command
with the full path to a Python executable. The module was verified using the
bundled Python 3.12.14 and SQLite 3.53.1. Run the build before the tests because
integration tests use the two supplied datasets and the generated catalog.

```powershell
./.venv/Scripts/python.exe -B -m intellimarket_rag search --platform flipkart --product-id SRTEH2FF9KEDEFGF --name "cycling shorts" --category Shorts --keywords "cotton lycra" --sort relevance
./.venv/Scripts/python.exe -B -m intellimarket_rag search --platform myntra --brand Roadster --colour Blue --min-price 500 --max-price 2000 --min-rating 4 --sort price-asc --limit 3
./.venv/Scripts/python.exe -B -m intellimarket_rag search --platform flipkart --price-field retail --min-price 35 --max-price 35
```

Run `search --help` for all options. Product name uses case-insensitive
substring search. Brand, colour, and category are normalized exact filters.
Product IDs use source identifiers, such as Myntra `17048614` without the
CSV's decimal suffix. Numeric ranges are inclusive. SQLite FTS5 requires all
supplied keyword tokens and can sort matching rows by relevance. Combine
keyword search with any structured filters. Price sort follows `--price-field`.
Missing prices or ratings are excluded by numeric bounds and sort last otherwise.

## Catalog, lineage, and data quality

- `artifacts/catalog.sqlite3` contains one product per platform and normalized
  source ID. SQLite FTS5 indexes searchable names and source evidence.
- `source_records` stores every logical CSV record, including exclusions and
  exact duplicates. It preserves the original fields apart from export index
  columns, source record IDs, normalized evidence, and duplicate links. A
  record number starts at 1 after the header and counts logical CSV records
  even when a description spans several physical lines.
- `accepted` counts valid distinct payloads, `duplicate` counts redundant valid
  payloads, and `excluded` counts unusable rows. All three statuses sum to
  the raw count. Several accepted records can represent the same product.
- The catalog uses agreed nonmissing values when a source ID repeats. Conflicting
  attributes are withheld individually and preserved with their contributing
  record numbers in `products.conflicts`. A conflicting title uses the first
  source title as its display label, with alternatives in the same conflict
  record. Descriptions, prices, URLs, and dates remain available at the source
  record level when their catalog value is withheld.
- Flipkart category labels come from the original category tree. Myntra has
  no category column. Its category filter covers a limited title-based
  taxonomy, marked `inferred_from_title`; ambiguous or unmatched titles remain
  uncategorized. Colour on Flipkart is extracted from exact Color/Colour
  specification keys when the values agree.
- `artifacts/ingestion_report.json` records counts, sentinel and null counts,
  parse issues, conflicting fields, SHA-256 digests, database size, execution
  time, and integrity checks. A source missing count includes blank fields and
  recognized missing markers, e.g. `No rating available` and `NA`.
- The build stages a fresh database inside `artifacts/` and replaces the active
  database after validation. Stop other builds and close any SQLite viewers
  before rebuilding, especially on Windows. Paths are relative to the
  chatbot working directory.

## Historical prices

Flipkart prices were observed during the supplied 2015–2016 crawl. Myntra's
observation date is unspecified. Neither dataset establishes live price,
availability, or currency. The default recorded price is Flipkart's
`discounted_price` or Myntra's `price`. Flipkart's `retail_price` is separate.
SQLite stores amounts in hundredths of the dataset's unit. Divide
`price_minor` or `retail_price_minor` by 100 for display. A null amount
means unavailable or conflicting in the catalog, with detail in source records.

## Phase 3 semantic indexing

Use the same virtual environment and the existing SQLite catalog. The commands
below install the semantic dependencies separately from the standard-library
catalog. Keep model files and temporary installation files within this module.

```powershell
# Run from rag_chatbot/
New-Item -ItemType Directory -Force artifacts/tmp | Out-Null
$env:TEMP = (Resolve-Path artifacts/tmp).Path
$env:TMP = $env:TEMP
$env:HF_HOME = Join-Path $PWD 'artifacts/model-cache'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
./.venv/Scripts/python.exe -B -m ensurepip
./.venv/Scripts/python.exe -B -m pip --disable-pip-version-check --no-cache-dir install torch --index-url https://download.pytorch.org/whl/cpu
./.venv/Scripts/python.exe -B -m pip --disable-pip-version-check --no-cache-dir install '.[semantic]'
./.venv/Scripts/python.exe -B -m intellimarket_rag index --device cpu --threads 6 --batch-size 48
./.venv/Scripts/python.exe -B -m intellimarket_rag semantic "Waterproof bags for carrying school supplies" --top-k 5
./.venv/Scripts/python.exe -B -m intellimarket_rag semantic "A denim jacket with button closure" --platform myntra --top-k 5
./.venv/Scripts/python.exe -B -m intellimarket_rag evaluate-semantic
./.venv/Scripts/python.exe -B -m unittest discover -s tests -v
```

The first index build downloads the pinned BGE small English model. Later
builds reuse an active index when the SQLite SHA-256, input checksums, model
revision, and document settings match. The build prints product and chunk
counts to stderr, and the command prints the final manifest to stdout. Use
`--device cuda` with a CUDA-enabled PyTorch distribution compatible with the
installed NVIDIA driver, or `--device auto` to select CUDA when available. Reduce
`--batch-size` if the selected device runs out of memory. The semantic tests
require a complete local index, and can run on CPU against an index built on GPU.
For Phase 2 tests alone, run `unittest discover -s tests -p test_catalog.py -v`.

To keep the CPU build and try CUDA side by side on a Windows machine with a
compatible NVIDIA driver, install the GPU build under the same virtual
environment and select it in the current PowerShell session:

```powershell
./.venv/Scripts/python.exe -B -m pip --disable-pip-version-check --no-cache-dir install --no-deps --target .venv/Lib/cuda-packages "torch==2.8.0" --index-url https://download.pytorch.org/whl/cu126
$ragPreviousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = Join-Path $PWD '.venv/Lib/cuda-packages'
./.venv/Scripts/python.exe -B -m intellimarket_rag index --device cuda --threads 4 --batch-size 48
$env:PYTHONPATH = $ragPreviousPythonPath
```

### Index and source attribution

The build uses normalized catalog descriptions, attributes, and specifications.
Documents omit structured prices, ratings, timestamps and identifiers and strip
common promotional passages and embedded links. The tokenizer splits long
documents at a 224-token budget, plus the model's special tokens. Vectors are
normalized and stored as 384 float32 values in LanceDB. The BGE retrieval
instruction applies to queries. Exact cosine search ranks chunks, then
keeps the highest-scoring chunk per catalog product. Search returns authoritative
SQLite facts and source file and record numbers. The similarity score is a
cosine similarity, with no calibrated probability interpretation.

`artifacts/semantic/active.json` refers to a completed, immutable build directory.
Each build has a `manifest.json` and a `lancedb/` table. The active pointer
changes after the new build validates. An interrupted run may leave an inactive
directory for inspection. Searches reject an active index built against a
different catalog. After Phase 2 changes the catalog, rerun `index`.

`evaluation/semantic_queries.jsonl` contains reviewed examples tied to real
source product IDs. `evaluate-semantic` writes per-query ranks and warm search
timings to `artifacts/semantic_evaluation.json`. The labels cover selected
positive examples. Recall@10 and MRR@10 on this set can miss relevant
alternatives and similar catalog variants.

## Phase 4 hybrid retrieval and comparison

Use the existing virtual environment, catalog and active semantic index. From
`rag_chatbot/` in PowerShell:

```powershell
./.venv/Scripts/python.exe -B -m intellimarket_rag hybrid 'cotton lycra shorts on Flipkart under 500; brand:Alisha'
./.venv/Scripts/python.exe -B -m intellimarket_rag hybrid 'platform:myntra; brand:Roadster; colour:Blue; price>=500; price<2000; rating>=4; rating-count>10; sort:price-asc' --top-k 5
./.venv/Scripts/python.exe -B -m intellimarket_rag hybrid 'platform:myntra; id:17048614'
./.venv/Scripts/python.exe -B -m intellimarket_rag hybrid 'a jacket with snap buttons; platform:myntra; colour:Black' --mode rerank
./.venv/Scripts/python.exe -B -m intellimarket_rag compare myntra 17685166 --top-k 3
./.venv/Scripts/python.exe -B -m intellimarket_rag evaluate-hybrid
./.venv/Scripts/python.exe -B -m unittest discover -s tests -v
```

Use free text for product descriptions and semicolon-delimited fields for
hard filters. Supported fields include `platform`, `brand`, `colour`,
`category`, `id`, `name`, `price-field`, and `sort`. `name` is an exact
case-insensitive title filter. Prices, ratings and rating counts use
`<`, `<=`, `=`, `>=`, and `>`, for example `price>1000; rating-count>=20`.
The parser recognizes selected phrases such as `on Myntra`, `under 500`,
`price between 500 and 1000`, and `cheapest first`. Use explicit filters
for other constraints. Unsupported or contradictory filter expressions return
a clarification error. The typed `Query` and `Bound` objects provide a separate
entry point for a future intent parser.

Structured requests use the full SQL-eligible set for sorting. Mixed
requests first restrict candidate eligibility, then rank or sort within the
retrieved candidate union. The keyword branch uses weighted FTS5 BM25 and
the semantic branch uses exact LanceDB search with prefilters. RRF combines
the two ranked lists by product ID. Tune local execution with the
`--keyword-pool`, `--semantic-pool`, `--rrf-k`, `--keyword-weight`,
`--semantic-weight`, and `--top-k` options. The optional `rerank` mode
uses title and evidence term coverage on a bounded pool with no additional
model. FTS5 baseline mode is `--mode fts`; dense-only mode is
`--mode semantic`.

Comparison starts from one exact source product ID. The identity rule requires
shared brand and model or style code, compatible category, substantial name
overlap, colour and material corroboration, and no detected conflicts.
Candidates may instead be similar, ambiguous, or yield no reliable match.
Price fields retain their specific dataset meanings, and each offer includes
its source records and historical-price notice.

The evaluation writes `artifacts/hybrid_evaluation.json`. It retains the
original 30-query labels and reports expanded development and held-out cases
separately. Ranked candidates in the report are automatically generated;
`evaluation/pooled_reviews.jsonl` records judgments checked against the catalog.
Structured expectations come from independent SQL fixtures. Exact catalog
matches, sort/filter checks, ambiguity handling, and comparisons are tracked
separately from graded retrieval metrics.

## Phase 5 standalone chatbot

From `rag_chatbot/` in PowerShell, reuse the current catalog, index and virtual
environment. The default provider is deterministic fallback. It runs locally
and supports discovery, exact filters, citations, product references, and
comparisons without sending catalog evidence to an API.

The default catalog and active index resolve from the chatbot package location.
From the repository root, use the checkout launcher in PowerShell:

```powershell
.\rag_chatbot\.venv\Scripts\python.exe -B -X utf8 .\rag_chatbot\run_chatbot.py chat --provider fallback
```

Use `--root` to select a different project directory, or `--catalog` and
`--index-dir` to select a specific SQLite file and the directory containing
`active.json`. Explicit relative paths resolve from your working directory.
The index manifest must match the selected catalog. A SQLite open error now
shows the resolved path to help distinguish a missing file from a Windows
read-permission problem.

```powershell
$env:HF_HUB_OFFLINE = '1'  # After the Phase 3 model is cached
./.venv/Scripts/python.exe -B -X utf8 -m intellimarket_rag chat --provider fallback --debug
./.venv/Scripts/python.exe -B -X utf8 -m intellimarket_rag evaluate-chat --provider fallback
./.venv/Scripts/python.exe -B -m unittest discover -s tests -v
```

Try these as successive turns:

1. `platform:myntra; brand:Roadster; price<=2000; sort:price-asc`
2. `Only show blue ones.`
3. `Tell me more about the second product.`
4. `Does it have pockets?`
5. `Compare the first and third products.`
6. `Remove the price restriction.`
7. `/reset`

`/exit` closes the CLI. Product positions refer to the last displayed result list.
Details keep that order and set the active product for “it.” New searches
start with fresh filters. Price and colour follow-ups carry the active query
forward. Comparison between displayed products describes the selected listings.
For cross-platform matching, use `compare; platform:myntra; id:17685166`.

Supported natural attribute phrases include “women's cotton kurtas”, “black
denim jackets with snap buttons”, “a poncho made from modal”, and “floral
print”. SQL applies these filters before keyword or vector ranking. You can
also use `fabric:cotton`, `bottom-fabric:rayon`, `material:leather`,
`gender:women`, `colour:black`, `pattern:floral`, `occasion:casual`, or
`closure:snap button`. A cotton search uses documented cotton aliases from
the recorded main fabric field. Choose `fabric:cotton blend` for recognized
blends, `fabric:cotton lycra` for that combination, and `fabric:pure cotton`
for an explicit purity label. Brand, descriptions and lining fabric cannot
establish the main fabric. Missing or conflicting fabric evidence is excluded.
For Myntra only, an unambiguous audience label immediately following the
recorded brand in the source title can support a gender filter when the
structured audience field is missing.
Unsupported negative or alternative attribute expressions ask for clarification.
“Only show pure cotton ones” updates the fabric while keeping the other filters.

The router uses SQL for IDs, exact titles and structured-only requests, FTS5
for short keyword queries, dense search for explicit similarity language,
and hybrid RRF for descriptive requests. Try `--rerank`, use
`--keyword-limit` to configure the short-query threshold, or use
`--mode fts`, `semantic`, `hybrid`, or `rerank` to override textual routing.
Use `--debug` for JSON diagnostics. Startup reports the requested and configured
providers. Each turn reports which provider contributed to the answer, the intent
provider, retrieval strategy and counts, timings, and available token usage.
`gemini_inference_succeeded` means at least one Gemini call returned a structured
completion. Check `provider_stages` to see whether that completion passed local
validation. A null value means Gemini was skipped or unavailable at startup.
`fallback_triggered` indicates a configuration, provider, or validation failure.
An intentional SQL or session lookup instead reports `deterministic_reason`.
Diagnostics use fixed reason codes and omit credentials, response bodies, and
environment values.

The CLI uses deterministic intent parsing by default. Text discovery normally
makes one provider call for evidence selection. SQL and session lookups
need no provider call. Use `--llm-intent` to opt in to a separate intent
refinement call. On a Gemini generation response with missing text, malformed
JSON or an output-token cutoff, the service can retry once with one product
and fewer fields. A response naming an unknown product or undisclosed field
is rejected locally. Exact prices, ratings and citations come from SQLite.

In `--debug` output, `generation_attempts` distinguishes provider finish
reasons, empty or malformed JSON, and evidence validation failures. Error
paths use schema field names and numeric positions. Response byte counts and
thought-token counts are included when available. The first dense turn shows
catalog and manifest checks, LanceDB open, model load, and any broad-filter
projection build under `timing_ms.retrieval_initialization`. Later turns in
the same process reuse these resources. Short FTS5 searches can run before
the dense model is loaded. Broad price filters use exact cosine scoring
over a cached projection of the existing vectors.

### Google Gemini

Install the optional official SDKs into the existing environment:

```powershell
New-Item -ItemType Directory -Force artifacts/tmp | Out-Null
$env:TMP = (Resolve-Path artifacts/tmp).Path
$env:TEMP = $env:TMP
./.venv/Scripts/python.exe -B -m pip --disable-pip-version-check --no-cache-dir install 'google-genai>=1,<3' 'ollama>=0.4,<1'
$env:GEMINI_API_KEY = Read-Host -MaskInput 'Gemini API key'
$env:GEMINI_MODEL = Read-Host 'Supported Gemini model ID'
./.venv/Scripts/python.exe -B -X utf8 -m intellimarket_rag chat --provider gemini
# Runs the labeled cases with real provider calls for eligible turns.
./.venv/Scripts/python.exe -B -X utf8 -m intellimarket_rag evaluate-chat --provider gemini
Remove-Item Env:GEMINI_API_KEY
```

For a live smoke test and evaluation with the model used here, run from
`rag_chatbot/` in the PowerShell session where you set `GEMINI_API_KEY`:

```powershell
if (-not $env:GEMINI_API_KEY) { throw 'Set GEMINI_API_KEY in this session first.' }
./.venv/Scripts/python.exe -B -X utf8 -m intellimarket_rag chat --provider gemini --model gemini-3.8-flash --debug
$report = ./.venv/Scripts/python.exe -B -X utf8 -m intellimarket_rag evaluate-chat --provider gemini --model gemini-3.8-flash | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Chat evaluation failed.' }
$report | Select-Object requested_provider, provider, startup_fallback_reason, actual_answer_providers, gemini_turns_with_successful_inference, fallback_turns, tokens
if (-not $report.actual_answer_providers.gemini) { throw 'No evaluated answer used a validated Gemini response.' }
```

For the smoke test, enter `Find women's cotton kurtas under 1500` twice in the
same session, then `Tell me more about the second product.` Check that the
search reports `actual_provider: gemini` and a generation stage of
`succeeded`. The product follow-up uses SQLite and has zero LLM latency.
To measure cold and warm dense retrieval, repeat the same test in a new CLI
process with `--mode hybrid`. Gemini 3.8 Flash uses low thinking by default.
Set `GEMINI_THINKING_LEVEL` to `low`, `medium`, or `high` to override it.

Choose a model that supports JSON structured output in your Google AI Studio
project. The model name is required and configurable. Hosted mode sends the
user turn, bounded recent user context for intent assistance, and a subset of
the retrieved catalog evidence to Gemini. Use fallback or local Ollama when
you want to keep all processing on the machine. [.env.example](.env.example)
documents the process environment variables. The application reads environment
variables directly. Real `.env` files are ignored by Git.

### Local Ollama

Use an already installed and running Ollama service and a compatible model
already present on the machine. The chatbot does not pull a model.

```powershell
ollama list
$env:OLLAMA_HOST = 'http://127.0.0.1:11434'
$env:OLLAMA_MODEL = Read-Host 'Installed Ollama model name'
./.venv/Scripts/python.exe -B -X utf8 -m intellimarket_rag chat --provider ollama
./.venv/Scripts/python.exe -B -X utf8 -m intellimarket_rag evaluate-chat --provider ollama
```

Provider connection settings, context budget, output tokens, timeout and
bounded retries are configurable through the environment. Rate-limit and
transport failures fall back to deterministic answers. Strict validation keeps
explicit constraints and references under application control. Ambiguous or
unsupported hard filters ask for clarification. The model selects fact keys
from provided evidence. Catalog records supply the displayed values, product
IDs, and citations, and the application decides cross-platform identity.
Missing or conflicting fields are identified in the answer. All amounts are
historical and currency is unspecified.

Evaluation writes `artifacts/chat_evaluation.json` and
`artifacts/chat_transcripts.txt`. Fallback runs report local timings and
leave provider token usage empty. Unit tests exercise provider protocol and
rejection paths with scripted responses. A provider evaluation can overwrite
the last report, so retain a copy if comparing modes.

## Phase 6 REST API

See the [standalone API integration guide](API.md) for PowerShell startup
commands, Swagger and OpenAPI endpoints, session behavior, example payloads,
and local deployment limits.
