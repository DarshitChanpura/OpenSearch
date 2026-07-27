# PoC Results — FILTERED ALIAS

Restricted view = a **term-filtered alias** over the full source index. No copy
is made: queries run over the whole shard and the filter narrows the result set.
This is architecturally identical to the security plugin's DLS post-filtering.
Compare against the sibling `poc/materialized-view` branch, whose `RESULTS.md`
has the identical structure.

## Environment

| | |
|---|---|
| OpenSearch | 3.7.0 (Lucene 10.4.0), single-node Docker, security plugin disabled |
| Host | 64 vCPU, 495 GB RAM; JVM heap 4 GB |
| Index | 1 primary shard, 0 replicas, force-merged to 1 segment |
| Corpus | synthetic patient records; 10 departments; **cardiology = 10% visible** |
| Restricted role | may read only `dept = cardiology` |

All runs are **local**. No production endpoint was ever touched.

**Reproduce:** `python3 poc/setup.py && python3 poc/security_demo.py && python3 poc/bench.py && python3 poc/scale.py`

The view under test:

| | |
|---|---|
| **Mechanism** | filtered alias — term-filtered pointer at the full source index, no copy |
| **Physical copy?** | No (`mechanism.HAS_PHYSICAL_COPY = False`) |
| **Query target** | the alias (executes over the full source shard) |

---

## 1. Storage & indexing (200k-doc corpus)

| Metric | Source index | Filtered alias | Ratio |
|---|---|---|---|
| Documents | 200,000 | 0 (no copy) | 0% |
| Store size | 36.0 MB | 0 bytes | **0%** |
| Index throughput | 29,269 docs/s | — (no build) | — |
| Write amplification with 1 view | — | — | **1.00×** |

**Reading:** the alias is a filtered pointer at the source — it copies nothing,
costs zero storage, and is always fresh. Write amplification is 1.0× regardless
of how many aliases you define.

---

## 2. Security: the side-channel (ExactOracle)

A term appearing only in hidden documents has a higher corpus-wide `df`, lowering
its BM25 IDF. Injecting one visible probe doc per term and comparing its score to
a fresh control reveals whether the term exists in hidden docs.

| Queried through | Secret terms leaked | Avg score gap (control − secret) |
|---|---|---|
| **Filtered alias** | **8 / 8** | 5.6547 |

**Reading:** all 8 hidden-only terms are trivially detectable — the probe scores
measurably lower than a fresh control (avg secret 2.99 vs. control 8.64). The
alias narrows results but scores against **every** document in the shard, so the
hidden `df` depresses the score. **The side-channel is fully present** — this is
the DLS leak the paper describes.

---

## 3. Search latency by query type (200k corpus)

p50 / p95 / p99 in milliseconds, 200 iterations after warmup. The view and the
source baseline (source index + explicit dept filter) return **identical visible
result counts** (parity confirmed).

| Query type | Visible hits | source baseline | filtered alias |
|---|---|---|---|
| `term` (keyword) | 394 | 1.13 / 1.32 / 1.41 | 1.18 / 1.40 / 1.46 |
| `match` (BM25 full-text) | 7,858 | 1.70 / 1.82 / 1.88 | 1.66 / 1.80 / 1.85 |
| `match_phrase_prefix` | 770 | 1.35 / 1.49 / 1.55 | 1.33 / 1.48 / 1.57 |
| `range` (numeric) | 10,000 | 1.62 / 1.78 / 1.88 | 1.61 / 1.77 / 1.87 |
| `terms` aggregation | 10,000 | 0.64 / 0.78 / 0.82 | 0.63 / 0.77 / 0.81 |
| `cardinality` aggregation | 10,000 | 1.02 / 1.13 / 1.19 | 1.01 / 1.12 / 1.18 |
| `bool` (match + range filter) | 6,255 | 1.78 / 1.92 / 1.99 | 1.77 / 1.91 / 1.98 |

**Reading:** the alias tracks the source baseline almost exactly — it *is* the
source index with a filter, so it scans the same postings. It buys correctness of
the result set but no latency advantage: it still pays to scan the hidden 90%.

---

## 4. Scaling: how latency grows (visible fraction fixed at 10%)

`match` (BM25) p99 latency captured at each corpus size.

| Total docs | Visible docs | Source size | Alias store | source baseline p99 (ms) | filtered alias p99 (ms) |
|---:|---:|---:|---:|---:|---:|
| 50,000 | 5,000 | 14.8 MB | 0 | 1.22 | 1.23 |
| 100,000 | 10,000 | 29.2 MB | 0 | 1.43 | 1.38 |
| 200,000 | 20,000 | 58.0 MB | 0 | 1.87 | 1.91 |
| 400,000 | 40,000 | 115.5 MB | 0 | 2.38 | 2.37 |
| 800,000 | 80,000 | 230.3 MB | 0 | 2.86 | 2.86 |

**Alias p99 grows with total corpus size** (1.23 → 2.86 ms across 50k–800k)
because it scans the whole shard, including the hidden documents the restricted
role can never see. Storage stays at 0 at every scale.

### Extrapolation

| Total docs | Source storage | Alias storage | Alias `match` p99 |
|---:|---:|---:|---:|
| 2,000,000 | 0.58 GB | 0 | ~4.4 ms |
| 10,000,000 | 2.92 GB | 0 | ~15 ms |
| 50,000,000 | 14.6 GB | 0 | ~70 ms |

The alias's latency grows linearly with the *total* corpus, so the cost of hiding
data the user can't see compounds with corpus size. It never pays storage —
that is the trade against the materialized view. Treat the multipliers as
order-of-magnitude — real clusters add shard fan-out and cache effects.

---

## 5. Bottom line (filtered alias)

- **Side-channel:** fully present (8/8) — scoring uses full-shard `df`.
- **Storage:** zero; write amplification 1.0×; always fresh.
- **Latency:** grows with *total* corpus — no advantage over scanning the full
  index, because that is exactly what it does.
- **Dynamic filters:** supports per-user / templated predicates (unlike the MV).

See the `poc/materialized-view` branch for the physical-isolation alternative
that **closes** the side-channel and keeps latency flat, at the cost of storage
and refresh-bounded freshness.

> The proposed **filter-aware alias** (see `rfc-filter-aware-aliases.md`) keeps
> this branch's zero-storage, always-fresh profile but pushes the filter *into*
> the statistics layer, so it closes the side-channel too. This branch measures
> the plain filtered alias / DLS behavior it improves on.
