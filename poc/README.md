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
```

Each writes a `*_metrics.json` next to the scripts; `RESULTS.md` summarizes them.

## Files

| File | Purpose |
|---|---|
| `mechanism.py` | **the only file that differs between branches** — defines the filtered alias: how the view is created, where probe writes land, whether it keeps a physical copy |
| `lib.py` | corpus generator, HTTP helpers, latency/percentile utilities, shared config |
| `setup.py` | builds source + view; measures storage + indexing throughput |
| `security_demo.py` | local ExactOracle BM25 side-channel test through the view |
| `bench.py` | p50/p95/p99 latency across 7 query types (view vs source baseline) |
| `scale.py` | rebuilds corpus at 5 sizes; storage + latency scaling for extrapolation |

## Model / caveats

- **Security disabled** in the container so the harness can inject probe docs
  directly. The filtered alias is a genuine OpenSearch construct; here it stands
  in for the security plugin's DLS post-filtering, which shares the same
  full-shard scoring path and therefore the same side-channel.
- Single shard, force-merged, warm cache: isolates the corpus-size effect but
  omits shard fan-out and cold-cache behavior. Extrapolations in `RESULTS.md`
  are order-of-magnitude.
