# Access-Control PoC — FILTERED ALIAS branch

Empirical PoC for exposing a restricted subset of an OpenSearch index via a
**filtered alias**: a term-filtered alias over the full source index that makes
no copy. This is architecturally identical to the security plugin's DLS
post-filtering — the query runs over the whole shard and the filter only narrows
the result set. Measures the BM25 side-channel, storage, indexing, and search latency.

> This is one of a matched pair of branches. The **`poc/materialized-view`** and
> **`poc/filtered-aliases`** branches are byte-identical except for
> **`poc/mechanism.py`** — diff those two files to see exactly how the mechanisms
> differ, and diff `RESULTS.md` to see the consequences.
>
> ```
> git diff poc/filtered-aliases poc/materialized-view -- poc/mechanism.py
> ```

Backs `rfc-filter-aware-aliases.md`. Results: [`RESULTS.md`](RESULTS.md).

## Safety

Runs **only** against a local OpenSearch on `http://localhost:9200` (override
with `OS_ENDPOINT`). It never uses any production endpoint or credentials.

## Prerequisites

Docker + Python 3 (stdlib only; no pip installs needed).

```bash
docker run -d --name os-bench -p 9200:9200 \
  -e discovery.type=single-node \
  -e DISABLE_SECURITY_PLUGIN=true \
  -e DISABLE_INSTALL_DEMO_CONFIG=true \
  -e "OPENSEARCH_JAVA_OPTS=-Xms4g -Xmx4g" \
  opensearchproject/opensearch:3.7.0
```

## Run (from the repo root)

```bash
python3 poc/setup.py          # build source + filtered alias; storage/indexing metrics
python3 poc/security_demo.py  # ExactOracle: filtered alias leaks 8/8
python3 poc/bench.py          # search latency by query type @ 200k docs
python3 poc/scale.py          # storage + latency scaling curve (50k .. 800k)
python3 poc/verify.py         # ground-truth correctness gate (see below)
```

Each writes a `*_metrics.json` next to the scripts; `RESULTS.md` summarizes them.

## Verifying correctness (`verify.py`)

The latency benchmarks rely on BM25 *scores*. `verify.py` deliberately does **not**
trust scores: it reads the raw Lucene term-dictionary `doc_freq` (the exact signal
the ExactOracle exploits) directly via `_termvectors`, and asserts four invariants,
exiting non-zero on any failure:

1. The MV physically holds only the visible (cardiology) subset — zero hidden docs.
   (On this branch the alias keeps no copy, so `verify.py` builds the MV directly
   for the term-dictionary comparison — the gate is mechanism-agnostic.)
2. Each hidden-only secret term has `df > 0` in the source term dictionary but
   `df == 0` in the MV — proven from the term dictionary, no scoring involved.
3. **Negative control:** a *visible* term is present in *both* dictionaries — so
   invariant 2 is real isolation, not just "the MV is smaller."
4. Source `df` strictly exceeds MV `df` for every leak term (the leak magnitude).

Two independent measurement paths — score-based (`security_demo.py`) and
structure-based (`verify.py`) — agreeing is what rules out a harness that fools
itself. A representative passing run is shown at the bottom of this file.

## Files

| File | Purpose |
|---|---|
| `mechanism.py` | **the only file that differs between branches** — defines the filtered alias: how the view is created, where probe writes land, whether it keeps a physical copy |
| `lib.py` | corpus generator, HTTP helpers, latency/percentile utilities, shared config |
| `setup.py` | builds source + view; measures storage + indexing throughput |
| `security_demo.py` | local ExactOracle BM25 side-channel test through the view |
| `bench.py` | p50/p95/p99 latency across 7 query types (view vs source baseline) |
| `scale.py` | rebuilds corpus at 5 sizes; storage + latency scaling for extrapolation |
| `verify.py` | ground-truth correctness gate: reads raw term-dictionary `df` (score-independent); fails non-zero if isolation breaks |

## Model / caveats

- **Security disabled** in the container so the harness can inject probe docs
  directly. The filtered alias is a genuine OpenSearch construct; here it stands
  in for the security plugin's DLS post-filtering, which shares the same
  full-shard scoring path and therefore the same side-channel.
- Single shard, force-merged, warm cache: isolates the corpus-size effect but
  omits shard fan-out and cold-cache behavior. Extrapolations in `RESULTS.md`
  are order-of-magnitude.

## Representative `verify.py` run (200k corpus)

```
source=200000 docs, MV=20000 docs (10.0% visible)

Invariant 1 — MV contains only the visible (cardiology) subset
  [PASS] MV has ZERO non-cardiology docs  — non-cardiology docs in MV = 0
  [PASS] MV size ≈ 10% of source  — ratio = 0.100

Invariant 2 — secret-term document frequency (raw term dictionary)
    hunter2        source_df=3368   mv_df=0
    acmemerger     source_df=3387   mv_df=0
    infarction     source_df=3389   mv_df=0
    confidential   source_df=3346   mv_df=0
    quarterly      source_df=3304   mv_df=0
    projections    source_df=3284   mv_df=0
    revenue        source_df=3469   mv_df=0
    diagnosis      source_df=3460   mv_df=0
  [PASS] every secret term is PRESENT in source term dict (df>0)  — min source df = 3284
  [PASS] every secret term is ABSENT from MV term dict (df==0)  — max mv df = 0

Invariant 3 — negative control: a visible-doc term is in BOTH dicts
    visible term 'ikadd': source_df=1351  mv_df=149
  [PASS] visible term present in source (df>0)
  [PASS] visible term ALSO present in MV (df>0)

Invariant 4 — hidden docs inflate source df above MV df (the leak)
  [PASS] secret-term source df >> MV df for all leak terms  — 8/8

 RESULT: all 7 invariants hold. Confirmed WITHOUT relying on BM25 scores.
```

The source-side `df` values above are exactly what this branch's filtered alias
scores against — which is why its ExactOracle leaks 8/8. The MV-side `df==0` is
why the sibling branch does not.
