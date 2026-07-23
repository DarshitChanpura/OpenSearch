# PoC Results: DLS / Filtered Alias vs. Materialized View

Empirical numbers backing the two RFCs (`rfc-materialized-views.md`,
`rfc-filter-aware-aliases.md`) and the architecture doc
(`design-access-control-architectures.md`).

## Environment

| | |
|---|---|
| OpenSearch | **3.7.0 (Lucene 10.4.0)**, single-node Docker, security plugin disabled |
| Host | 64 vCPU, 495 GB RAM; JVM heap 4 GB |
| Index | 1 primary shard, 0 replicas, force-merged to 1 segment |
| Corpus | synthetic patient records; 10 departments; **cardiology = 10% visible** |
| Restricted role | may read only `dept = cardiology` |

All runs are **local**. The production endpoint in `reproduce.py` / `.os-creds`
was never touched.

**Reproduce:** `python3 poc/setup.py && python3 poc/security_demo.py && python3 poc/bench.py && python3 poc/scale.py`

Three mechanisms under test:

| Name | What it is |
|---|---|
| **alias_postfilter** | filtered alias over the full source index — architecturally identical to DLS post-filtering (query runs on all docs, filter applied to results) |
| **mv** | materialized view: a separate physical index holding only the 10% visible docs |
| **alias_prefilter** | `constant_score` wrap over the alias — a proxy for the filter-aware alias's Strategy B (non-ranked) cost profile |

---

## 1. Storage & indexing (from `setup.py`, 200k-doc corpus)

| Metric | Source index (DLS / alias) | Materialized view | Ratio |
|---|---|---|---|
| Documents | 200,000 | 20,000 | 10.0% |
| Store size | 58.3 MB | 6.0 MB | **10.3%** |
| Index throughput | 26,144 docs/s | 10,942 docs/s (refresh) | — |
| Write amplification with 1 MV | — | — | **1.10×** |

**Reading:**
- MV storage tracks the visible fraction almost exactly (10.3% of source ≈ the 10% visible docs). The physical copy is not "free" — for a role that sees 60% of an index the MV costs ~60% extra; for *k* roles you pay the sum.
- A filtered alias and DLS cost **0 bytes** — they add no index.
- Building/refreshing the MV re-indexes the visible subset: **10% write amplification per MV** here. With one MV per restricted role across *k* roles, amplification is `1 + Σ(visible_fraction_i)`.

---

## 2. Security: the side-channel (from `security_demo.py`)

Local reproduction of the paper's **ExactOracle**. A term appearing only in
hidden (non-cardiology) documents has a higher corpus-wide `df`, which lowers its
BM25 IDF. Injecting one visible probe doc per term and comparing its score to a
fresh control term reveals whether the term exists in hidden docs.

| Queried through | Secret terms leaked | Avg score gap (control − secret) |
|---|---|---|
| **Filtered alias (DLS post-filter)** | **8 / 8** | **5.65** |
| **Materialized view** | **0 / 8** | 0.0002 (float noise) |

**Reading:**
- Through the filtered alias, all 8 hidden-only terms are trivially detectable: the probe scores lower (IDF depressed by hidden-doc `df`) than a fresh control. The alias narrows *results* but scoring still consults full-shard statistics — **the side-channel is fully present.**
- Through the MV, the gap collapses to 0.0002 (BM25 length-norm rounding). The hidden docs were never copied, so there is no `df` signal to leak — **closed by construction.**
- This is the security case for physical isolation, and equally the motivation for filter-aware aliases: fix the statistics layer to get the same 0-leak result without the copy.

---

## 3. Search latency by query type (from `bench.py`, 200k corpus)

p50 / p95 / p99 in milliseconds, 200 iterations after warmup. All three return
**identical visible result counts** (parity confirmed).

| Query type | Visible hits | alias_postfilter (DLS) | materialized view | alias_prefilter (Strat. B) |
|---|---|---|---|---|
| `term` (keyword) | 394 | 2.77 / 3.33 / 3.77 | **1.69 / 1.96 / 2.29** | 1.89 / 2.15 / 2.56 |
| `match` (BM25 full-text) | 7,858 | 2.44 / 2.80 / 3.13 | **1.41 / 1.60 / 1.76** | 2.77 / 3.03 / 3.65 |
| `match_phrase_prefix` | 770 | 2.02 / 2.30 / 2.61 | **1.40 / 1.58 / 1.66** | 1.72 / 1.90 / 2.01 |
| `range` (numeric) | 10,000 | 2.17 / 2.41 / 2.85 | **1.16 / 1.36 / 1.48** | 1.86 / 2.03 / 2.29 |
| `terms` aggregation | 10,000 | 1.30 / 1.55 / 1.62 | 1.07 / 1.34 / 1.60 | **1.04 / 1.20 / 1.27** |
| `cardinality` aggregation | 10,000 | 1.48 / 1.66 / 1.71 | 1.35 / 1.53 / 1.62 | 1.37 / 1.51 / 1.54 |
| `bool` (match + range filter) | 6,255 | 2.21 / 2.47 / 2.85 | **1.31 / 1.46 / 1.55** | 1.93 / 2.11 / 2.37 |

**Reading:**
- The MV is fastest on nearly every query type because it scans 20k docs, not 200k. The largest wins are on the scoring/expansion-heavy types (`match` BM25, `match_phrase_prefix`, `bool`) — the same query types the side-channel exploits.
- `cardinality_agg` shows no MV advantage: HyperLogLog cost is dominated by distinct-value count (`user_id` has ~20k uniques in both), not doc count.
- `alias_prefilter` (constant_score) is faster than `alias_postfilter` on the aggregation/prefix queries but *slower* on `match` here (2.77 vs 2.44 p50) — at 200k the scoring-vs-no-scoring difference is inside the noise floor. Its value is a large-corpus claim; the scaling run (§4) is where the non-ranked path should be judged.
- **Caveat:** at 200k docs on a warm single shard, absolute latencies are dominated by HTTP + coordination overhead (~1 ms floor). The *ranking* is stable and directionally correct, but the absolute gaps are small here. The scaling run (§4) is where the divergence becomes decisive.

---

## 4. Scaling: how the gap grows (from `scale.py`)

Corpus rebuilt at 5 sizes, visible fraction fixed at 10%. Storage and
`match` (BM25) p99 latency captured at each.

| Total docs | Visible docs | Source size | MV size | MV/src | alias p99 (ms) | MV p99 (ms) |
|---:|---:|---:|---:|---:|---:|---:|
| 50,000 | 5,000 | 14.7 MB | 1.6 MB | 10.9% | 1.59 | 1.24 |
| 100,000 | 10,000 | 29.2 MB | 3.0 MB | 10.3% | 1.81 | 1.13 |
| 200,000 | 20,000 | 58.1 MB | 6.0 MB | 10.3% | 2.27 | 1.06 |
| 400,000 | 40,000 | 115.5 MB | 11.8 MB | 10.2% | 2.50 | 1.00 |
| 800,000 | 80,000 | 230.4 MB | 23.1 MB | 10.0% | 2.86 | 0.95 |

**Two clean trends:**
- **Storage is linear in total docs for both**, but the MV's constant is the visible fraction (~10%). Source storage is what DLS/aliases "reuse for free."
- **Alias (DLS) p99 grows with *total* corpus size; MV p99 is flat** (in fact slightly *decreasing* over this range — it only ever scans the visible subset). Least-squares fit:

  ```
  alias  p99 ≈ 1.720 ms + 1.57e-6 · total_docs      (grows with hidden data)
  MV     p99 ≈ 1.178 ms − 3.3e-7  · total_docs       (effectively flat)
  ```

### Extrapolation

Using the fitted slopes (and holding the MV at its measured ~1.0 ms floor, since
it scales with visible docs, not total):

| Total docs | Source storage | MV storage (1 role) | MV storage (10 roles) | alias/DLS `match` p99 | MV `match` p99 | MV speedup |
|---:|---:|---:|---:|---:|---:|---:|
| 2,000,000 | 0.58 GB | 0.06 GB | 0.58 GB | ~4.9 ms | ~1.0 ms | **~5×** |
| 10,000,000 | 2.92 GB | 0.30 GB | 2.92 GB | ~17.4 ms | ~1.0 ms | **~17×** |
| 50,000,000 | 14.6 GB | 1.50 GB | 14.6 GB | ~80.2 ms | ~1.0 ms | **~80×** |

**Reading:**
- The MV's search-latency advantage **compounds with corpus size** and with the ratio of hidden-to-visible data. The more a role is restricted (smaller visible fraction), the bigger the MV win — because DLS/aliases pay to scan data the user can't even see.
- The mirror-image cost: at 10 roles each seeing 10%, the MVs collectively re-store ~100% of the corpus (2.92 GB extra at 10M docs). This is the storage-vs-latency-vs-security trade the RFCs frame — MV buys latency + hard isolation with storage; filter-aware aliases buy isolation with a bounded query-time cost and zero storage. (The 50M source row rounds to 14.6 GB.)
- Extrapolation assumes the fitted linear slope holds and single-shard scan cost dominates; real clusters add shard fan-out, cache effects, and merge policy. Treat the multipliers (~5×/17×/80×) as order-of-magnitude, not guarantees.

---

## 5. Bottom line

| | DLS / filtered alias | Materialized view | Filter-aware alias (proposed) |
|---|---|---|---|
| Side-channel (measured) | **Leaks 8/8** | **0/8** | 0/8 (by design) |
| Storage | 0 | +10% per 10%-role (linear) | 0 |
| Search latency vs corpus | grows with **total** docs | flat (scales with **visible**) | baseline − scoring cost (Strat. B) to baseline + stats cost (Strat. A) |
| Indexing overhead | none | +10% write amp per MV | none |
| Freshness | live | bounded by refresh | live |

- If the goal is **confidentiality + low latency on a large mostly-hidden index**, the MV wins decisively and the storage cost is the visible fraction.
- If the goal is **confidentiality with zero storage and live data**, the filter-aware alias is the right tool; the `alias_prefilter` proxy shows its non-ranked path is faster than the scored post-filter on the aggregation/prefix classes.
- Plain DLS / filtered aliases are the only option that is both slower-at-scale *and* leaks. The measurements make the case for adding at least one of the two proposed mechanisms.
