# Access-Control PoC & Benchmark Harness

Empirical comparison of three ways to show a user a restricted subset of an
OpenSearch index — **DLS / filtered alias** (post-filter), **materialized view**
(physical isolation), and **filter-aware alias** (pre-filter, proxied) — across
security (side-channel), storage, indexing, and search latency.

Backs: `../rfc-materialized-views.md`, `../rfc-filter-aware-aliases.md`,
`../design-access-control-architectures.md`. Results: [`RESULTS.md`](RESULTS.md).

## Safety

Runs **only** against a local OpenSearch on `http://localhost:9200`. It never
uses the production endpoint/credentials in `../reproduce.py` / `../.os-creds`.

## Prerequisites

Docker + Python 3 (stdlib only; no pip installs needed).

```bash
# start a local single-node OpenSearch (security disabled for the harness)
docker run -d --name os-bench -p 9200:9200 \
  -e discovery.type=single-node \
  -e DISABLE_SECURITY_PLUGIN=true \
  -e DISABLE_INSTALL_DEMO_CONFIG=true \
  -e "OPENSEARCH_JAVA_OPTS=-Xms4g -Xmx4g" \
  opensearchproject/opensearch:3.7.0
```

The harness targets `http://localhost:9200` by default; override with the
`OS_ENDPOINT` env var to point at a different local cluster.

## Run (from the repo root)

```bash
python3 poc/setup.py          # build source + MV + filtered alias; storage/indexing metrics
python3 poc/security_demo.py  # ExactOracle: alias leaks 8/8, MV leaks 0/8 (score gap ~5.65)
python3 poc/bench.py          # search latency by query type @ 200k docs
python3 poc/scale.py          # storage + latency scaling curve (50k .. 800k)
```

Each writes a `*_metrics.json` next to the scripts; `RESULTS.md` summarizes them.

## Files

| File | Purpose |
|---|---|
| `lib.py` | corpus generator, HTTP helpers, latency/percentile utilities, shared config |
| `setup.py` | builds the three constructs; measures storage + indexing throughput |
| `security_demo.py` | local ExactOracle BM25 side-channel reproduction |
| `bench.py` | p50/p95/p99 latency across 7 query types |
| `scale.py` | rebuilds corpus at 5 sizes; storage + latency scaling for extrapolation |

## Model / caveats

- **Security disabled** in the container: the *filtered alias* stands in for DLS
  post-filtering. Both inject the role predicate as a filter over the shared
  physical index and apply it to results — architecturally identical for the
  side-channel and latency questions studied here.
- **`alias_prefilter`** wraps queries in `constant_score` as a cheap proxy for
  the filter-aware alias's Strategy B (non-ranked). A true implementation would
  compute filtered `CollectionStatistics`; the proxy captures the "skip scoring"
  cost profile, not the exact filtered-IDF cost.
- Single shard, force-merged, warm cache: isolates the corpus-size effect but
  omits shard fan-out and cold-cache behavior. Extrapolations in `RESULTS.md`
  are order-of-magnitude.
