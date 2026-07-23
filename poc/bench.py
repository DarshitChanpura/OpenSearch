"""Benchmark harness: search latency across query types for the three mechanisms.

Mechanisms compared per query type:
  1. alias_postfilter  — query the filtered alias (executes on the 200k source
                          index, alias filter auto-applied to results). This is
                          the DLS / filtered-alias status quo.
  2. mv                — query the materialized view index directly (20k visible
                          docs; no filter needed, docs already restricted).
  3. alias_prefilter   — Strategy B proxy: constant_score wrap over the alias.
                          Approximates the pre-filter cost profile of a
                          filter-aware alias for the non-ranked security case.

For each we record p50/p95/p99/mean latency (ms). Also captures result-count
parity so we can confirm all three return the same visible documents.

Emits poc/bench_metrics.json.
"""
import json
import lib

VDEPT = lib.VISIBLE_DEPT

# Query templates. {mech} is filled per mechanism where the shape differs.
# For the alias the dept filter is implicit (alias filter); for MV it's absent.
QUERY_TYPES = {
    "term_keyword": {
        "desc": "term filter on category (exact keyword)",
        "body": {"size": 10, "query": {"term": {"category": "cat-7"}}},
    },
    "match_fulltext_bm25": {
        "desc": "match query on content (BM25 scoring — where the oracle lives)",
        "body": {"size": 10, "query": {"match": {"content": "rwlssxf"}}},
    },
    "match_phrase_prefix": {
        "desc": "match_phrase_prefix on content (PrefixOracle query type)",
        "body": {"size": 10, "query": {"match_phrase_prefix": {"content": "ab"}}},
    },
    "range_numeric": {
        "desc": "range query on value",
        "body": {"size": 10, "query": {"range": {"value": {"gte": 50000}}}},
    },
    "terms_agg": {
        "desc": "terms aggregation on category",
        "body": {"size": 0, "aggs": {"c": {"terms": {"field": "category",
                                                     "size": 50}}}},
    },
    "cardinality_agg": {
        "desc": "cardinality aggregation on user_id",
        "body": {"size": 0, "aggs": {"u": {"cardinality": {"field": "user_id"}}}},
    },
    "bool_filter_combo": {
        "desc": "bool: match content + range filter (mixed scoring+filter)",
        "body": {"size": 10, "query": {"bool": {
            "must": [{"match": {"content": "rwlssxf"}}],
            "filter": [{"range": {"value": {"gte": 20000}}}]}}},
    },
}


def wrap_constant_score(body):
    """Strategy B proxy: strip scoring by wrapping query in constant_score."""
    b = json.loads(json.dumps(body))
    if "query" in b:
        b["query"] = {"constant_score": {"filter": b["query"]}}
    return b


def result_count(index, body):
    b = json.loads(json.dumps(body))
    b["size"] = 0
    r = lib.get(f"/{index}/_search", b)
    return r["hits"]["total"]["value"]


def main():
    results = {}
    for qname, q in QUERY_TYPES.items():
        body = q["body"]
        # constant_score cannot wrap an agg-only (no query) request meaningfully;
        # for those, prefilter proxy == same body (aggs already gate on filter).
        has_query = "query" in body
        cs_body = wrap_constant_score(body) if has_query else body

        entry = {"desc": q["desc"], "counts": {}, "latency": {}}

        # 1. alias post-filter (full 200k index, alias filter applied)
        entry["latency"]["alias_postfilter"] = lib.time_query(lib.ALIAS, body)
        entry["counts"]["alias_postfilter"] = result_count(lib.ALIAS, body)

        # 2. materialized view (20k index)
        entry["latency"]["mv"] = lib.time_query(lib.MV_INDEX, body)
        entry["counts"]["mv"] = result_count(lib.MV_INDEX, body)

        # 3. filter-aware alias pre-filter proxy (constant_score over alias)
        entry["latency"]["alias_prefilter"] = lib.time_query(lib.ALIAS, cs_body)
        entry["counts"]["alias_prefilter"] = result_count(lib.ALIAS, cs_body)

        results[qname] = entry
        p = entry["latency"]
        print(f"{qname:22s} "
              f"alias={p['alias_postfilter']['p50']:>6.2f}/{p['alias_postfilter']['p99']:>6.2f}  "
              f"mv={p['mv']['p50']:>6.2f}/{p['mv']['p99']:>6.2f}  "
              f"prefilter={p['alias_prefilter']['p50']:>6.2f}/{p['alias_prefilter']['p99']:>6.2f}  "
              f"(p50/p99 ms)  counts a={entry['counts']['alias_postfilter']} "
              f"mv={entry['counts']['mv']}")

    with open("poc/bench_metrics.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
