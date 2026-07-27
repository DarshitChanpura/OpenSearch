"""Benchmark: search latency across query types for THIS mechanism's view vs the
unrestricted source-index baseline.

This script is identical on both branches. On the filtered-alias branch the view
executes on the full source index (latency grows with total docs); on the
materialized-view branch it executes on a small separate index (latency tracks
the visible subset). Diff `mechanism.py` to see why.

For each query type we record p50/p95/p99/mean latency (ms) plus a result-count
parity check between the baseline (restricted with an explicit dept filter) and
the view. Emits poc/bench_metrics.json.
"""
import json
import lib
import mechanism

VDEPT = lib.VISIBLE_DEPT

# Query templates run against the view as-is. The baseline runs the same query
# with an explicit dept filter added so both return the identical visible set.
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


def with_dept_filter(body):
    """Baseline query: same query wrapped so it only sees the visible dept."""
    b = json.loads(json.dumps(body))
    dept = {"term": {"dept": VDEPT}}
    if "query" in b:
        b["query"] = {"bool": {"must": [b["query"]], "filter": [dept]}}
    else:
        # agg-only request: add a query that restricts to the visible dept
        b["query"] = dept
    return b


def result_count(index, body):
    b = json.loads(json.dumps(body))
    b["size"] = 0
    r = lib.get(f"/{index}/_search", b)
    return r["hits"]["total"]["value"]


def main():
    results = {"mechanism": mechanism.NAME, "queries": {}}
    for qname, q in QUERY_TYPES.items():
        body = q["body"]
        base_body = with_dept_filter(body)

        entry = {"desc": q["desc"], "counts": {}, "latency": {}}

        # baseline: full source index, explicit dept filter (the "before")
        entry["latency"]["baseline_source"] = lib.time_query(lib.SOURCE_INDEX, base_body)
        entry["counts"]["baseline_source"] = result_count(lib.SOURCE_INDEX, base_body)

        # this mechanism's view (the "after")
        entry["latency"]["view"] = lib.time_query(mechanism.VIEW_NAME, body)
        entry["counts"]["view"] = result_count(mechanism.VIEW_NAME, body)

        results["queries"][qname] = entry
        p = entry["latency"]
        print(f"{qname:22s} "
              f"baseline={p['baseline_source']['p50']:>6.2f}/{p['baseline_source']['p99']:>6.2f}  "
              f"view={p['view']['p50']:>6.2f}/{p['view']['p99']:>6.2f}  "
              f"(p50/p99 ms)  counts base={entry['counts']['baseline_source']} "
              f"view={entry['counts']['view']}")

    with open("poc/bench_metrics.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
