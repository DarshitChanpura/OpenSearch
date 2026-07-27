# PoC Results — MATERIALIZED VIEW

Restricted view = a **separate physical index** holding only the visible
(cardiology) documents. Compare against the sibling `poc/filtered-aliases`
branch, whose `RESULTS.md` has the identical structure.

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
| **Mechanism** | materialized view — separate physical index, visible docs only |
| **Physical copy?** | Yes (`mechanism.HAS_PHYSICAL_COPY = True`) |
| **Query target** | the MV index directly |

---

## 1. Storage & indexing (200k-doc corpus)

| Metric | Source index | Materialized view | Ratio |
|---|---|---|---|
| Documents | 200,000 | 20,000 | 10.0% |
| Store size | 58.4 MB | 6.0 MB | **10.2%** |
| Index throughput | 28,974 docs/s | 11,379 docs/s (refresh) | — |
| Write amplification with 1 view | — | — | **1.10×** |

**Reading:** the MV keeps a physical copy of the visible subset, so it costs
~10% extra storage (the visible fraction) and ~10% write amplification per view.
For *k* roles the amplification is `1 + Σ(visible_fraction_i)`.

---

## 2. Security: the side-channel (ExactOracle)

A term appearing only in hidden documents has a higher corpus-wide `df`, lowering
its BM25 IDF. Injecting one visible probe doc per term and comparing its score to
a fresh control reveals whether the term exists in hidden docs.

| Queried through | Secret terms leaked | Avg score gap (control − secret) |
|---|---|---|
| **Materialized view** | **0 / 8** | 0.0002 (float noise) |

**Reading:** the gap collapses to rounding noise. The hidden docs were never
copied into the MV, so the MV's `df` counts only the probe doc — identical to a
control term. **The side-channel is closed by construction.**

---

## 3. Search latency by query type (200k corpus)

p50 / p95 / p99 in milliseconds, 200 iterations after warmup. The view and the
source baseline (source index + explicit dept filter) return **identical visible
result counts** (parity confirmed).

| Query type | Visible hits | source baseline | materialized view |
|---|---|---|---|
| `term` (keyword) | 394 | 1.16 / 1.34 / 1.43 | **0.74 / 0.86 / 0.93** |
| `match` (BM25 full-text) | 7,858 | 1.71 / 2.02 / 2.27 | **0.87 / 1.02 / 1.11** |
| `match_phrase_prefix` | 770 | 1.38 / 1.60 / 1.73 | **0.85 / 0.97 / 1.02** |
| `range` (numeric) | 10,000 | 1.68 / 1.90 / 2.05 | **0.81 / 0.98 / 1.11** |
| `terms` aggregation | 10,000 | 0.71 / 0.84 / 0.88 | 0.70 / 0.83 / 0.88 |
| `cardinality` aggregation | 10,000 | 1.10 / 1.24 / 1.29 | 1.09 / 1.30 / 1.34 |
| `bool` (match + range filter) | 6,255 | 1.84 / 2.18 / 2.49 | **1.02 / 1.15 / 1.25** |

**Reading:** the MV is fastest on nearly every query type because it scans 20k
docs, not 200k. The largest wins are on the scoring/expansion-heavy types
(`match`, `match_phrase_prefix`, `bool`) — the same types the side-channel
exploits. `cardinality_agg` shows no advantage (HyperLogLog cost tracks distinct
values, not doc count).

---

## 4. Scaling: how latency grows (visible fraction fixed at 10%)

`match` (BM25) p99 latency captured at each corpus size.

| Total docs | Visible docs | Source size | MV size | MV/src | source baseline p99 (ms) | MV p99 (ms) |
|---:|---:|---:|---:|---:|---:|---:|
| 50,000 | 5,000 | 14.7 MB | 1.6 MB | 10.9% | 1.19 | 0.90 |
| 100,000 | 10,000 | 29.2 MB | 3.0 MB | 10.3% | 1.41 | 0.89 |
| 200,000 | 20,000 | 58.0 MB | 6.0 MB | 10.3% | 1.87 | 0.90 |
| 400,000 | 40,000 | 115.5 MB | 11.7 MB | 10.1% | 2.32 | 0.89 |
| 800,000 | 80,000 | 230.4 MB | 23.1 MB | 10.0% | 2.64 | 0.88 |

**MV p99 is flat** (~0.9 ms) because it only ever scans the visible subset,
regardless of how much hidden data the source accumulates. Storage grows linearly
at ~10% of source.

### Extrapolation

| Total docs | Source storage | MV storage (1 role) | MV storage (10 roles) | source baseline `match` p99 | MV `match` p99 | MV speedup |
|---:|---:|---:|---:|---:|---:|---:|
| 2,000,000 | 0.58 GB | 0.06 GB | 0.58 GB | ~4.4 ms | ~0.9 ms | **~5×** |
| 10,000,000 | 2.92 GB | 0.30 GB | 2.92 GB | ~15 ms | ~0.9 ms | **~17×** |
| 50,000,000 | 14.6 GB | 1.50 GB | 14.6 GB | ~70 ms | ~0.9 ms | **~80×** |

The MV's latency advantage compounds with corpus size and with how restricted the
role is. The mirror cost: 10 roles each seeing 10% collectively re-store ~100% of
the corpus. Treat the multipliers as order-of-magnitude — real clusters add shard
fan-out and cache effects.

---

## 5. Bottom line (materialized view)

- **Side-channel:** closed by construction (0/8) — hidden docs are physically absent.
- **Storage:** +~10% per 10%-visible role (linear); write amplification 1.10× per view.
- **Latency:** flat, scales with the *visible* subset — decisively faster on large mostly-hidden indexes.
- **Freshness:** bounded by the refresh interval (the copy lags the source).
- **Bonus:** the copy step can also precompute / aggregate / project / reshape.

See the `poc/filtered-aliases` branch for the zero-storage, always-fresh
alternative that instead **leaks** the side-channel.
