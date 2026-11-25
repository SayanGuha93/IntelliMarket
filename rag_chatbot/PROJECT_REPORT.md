# IntelliMarket chatbot project report and viva notes

## Architecture and design decisions

The chatbot is a standalone Python application with a FastAPI adapter and a CLI. The ingestion pipeline validates CSV schemas, normalises prices and ratings, cleans HTML, parses source specifications and attributes, consolidates duplicates, and maintains source-row lineage in SQLite. Product documents are embedded with BAAI/bge-small-en-v1.5, a 384-dimensional encoder, and stored in LanceDB. SQLite supplies indexed structured queries and FTS5 keyword search.

For each turn, the service resolves intent and merges intentional changes with session context. Explicit price, fabric, colour and other supported constraints are enforced against verified catalog fields. For example, the Cotton Fab brand cannot qualify a Poly Crepe garment for a cotton filter. SQL handles exact filters and IDs, FTS5 handles lexical searches, and dense search adds semantic candidates for descriptive queries. Hybrid retrieval combines ranked results when the route benefits from both. Missing or conflicting attributes can reduce coverage for strict queries.

Gemini can choose from retrieved evidence on eligible turns. The application validates the response against the evidence and renders product details, prices and citations from catalog records. Exact lookups and other eligible routes can run deterministically. Provider failures retain a deterministic grounded response. Cross-platform comparison requires sufficient evidence for identity and can return similar products, ambiguity or no reliable match.

FastAPI provides a stable JSON contract. Local sessions use isolated bounded memory and idle expiration. Startup warmup loads the model and dense index before serving if enabled. The API can emit a coarse, opt-in server outcome for generation, independent of the public JSON response.

## Dataset and index statistics

| Metric | Flipkart | Myntra | Total |
|---|---:|---:|---:|
| Raw records | 20,000 | 14,330 | 34,330 |
| Accepted records | 20,000 | 14,267 | 34,267 |
| Excluded records | 0 | 19 | 19 |
| Duplicate records | 0 | 44 | 44 |
| Catalog products | 19,998 | 14,222 | 34,220 |

The catalog retains 34,330 lineage rows, including rows excluded from the product set. The dense index contains 42,962 chunks and vectors from 40,006 unique embedding computations. The Flipkart crawl spans 1 December 2015 through 28 June 2016 UTC. Myntra has no established price observation date. Prices and ratings are dataset values, with current price, availability and currency unverified.

## Retrieval, latency and validation

Historical labelled 30-query retrieval evaluations from development phases used Recall@10 and mean reciprocal rank (MRR). These scores describe the project evaluation set.

| Run | Recall@10 | MRR |
|---|---:|---:|
| Phase 3 dense | 40.56% | 0.325 |
| Phase 4 FTS5 | 71.67% | 0.619 |
| Phase 4 hybrid | 63.89% | 0.565 |
| Phase 4 hybrid with coverage rerank | 65.00% | 0.582 |
| Phase 5.3 adaptive with attribute enforcement | 68.33% | 0.571 |

Phase 3 dense search measured 91.5 ms mean and 110.3 ms p95. The Phase 5.3 adaptive evaluation measured 227.7 ms mean and 707 ms p95. Phase 6 loopback measurements without warmup were 0.404 s to start, 13.15 s for the first hybrid turn and 147/145 ms for two subsequent turns. With warmup, startup took 12.322 s and the three turns took 151/141/133 ms. These are local measurements from distinct workloads and exclude guarantees about deployment or provider latency.

| Suite | Result |
|---|---|
| Phase 5.3 fallback evaluation | 45/45 scenarios, 67 turns, including 18 multi-turn scenarios |
| Final live Gemini evaluation reported by the project owner | 45/45 scenarios, 67 turns, 11 successful Gemini answers, 56 deterministic answers, zero unexpected fallbacks. Mean end-to-end 696.35 ms and p95 4,205.63 ms. |
| Phase 6 regression | 86 passing automated tests |
| Phase 7 full regression | 88 passing automated tests in 42.982 s |
| Phase 7 loopback HTTP | UTF-8 verified on raw bytes. Deletion returned 204 with an empty body. Deleted and expired session requests returned 404. |
| Phase 7 Gemini transport check | Regression proved adapter wiring and outcome logging with a provider stub. The live-provider command uses the owner's private server environment. |

The automated suite uses the existing product artifacts and covers ingestion and retrieval logic, conversational context, explicit constraints, provider failure behavior and the REST contract. Phase 7 adds assertions for raw JSON encoding and server-only outcome logging. The labelled set is small. Missing metadata, historical records, uneven category coverage and Gemini network variability limit extrapolation.

## Viva discussion

- Why hybrid retrieval? Numerical and attribute filters need exact evidence, FTS5 finds literal terms, and embeddings help when descriptions use different words.
- How does the system prevent invented prices? The provider operates on enumerated evidence and the server renders claims from validated catalog IDs and source values.
- Why keep source rows? A citation traces a normalised product to a particular record and supports inspection when data disagrees.
- What does warmup achieve? It shifts model and index setup before readiness. It does not remove Gemini network time.
- What remains before production? Replace process-local sessions with authenticated shared storage and add TLS, traffic limits and operational controls. Live-commerce questions require separately verified current data.
