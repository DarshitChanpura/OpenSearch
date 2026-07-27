"""Multi-scale driver: rebuild the corpus at several total sizes and, at each,
measure storage and search latency for the unrestricted source baseline vs THIS
mechanism's restricted view.

This script is identical on both branches. On the filtered-alias branch the view
latency scales with TOTAL docs (it scans the whole shard); on the
materialized-view branch it scales with the VISIBLE subset (a separate index).
Diff `mechanism.py` to see why.

Visible fraction is fixed (~10%, cardiology). Emits poc/scale_metrics.json.
"""
import json
import time
import lib
import mechanism

SCALES = [50_000, 100_000, 200_000, 400_000, 800_000]

# representative query set (subset of bench.py, one per cost class)
QUERIES = {
    "term_keyword": {"size": 10, "query": {"term": {"category": "cat-7"}}},
    "match_bm25": {"size": 10, "query": {"match": {"content": "rwlssxf"}}},
    "match_phrase_prefix": {"size": 10,
                            "query": {"match_phrase_prefix": {"content": "ab"}}},
    "terms_agg": {"size": 0,
                  "aggs": {"c": {"terms": {"field": "category", "size": 50}}}},
    "cardinality_agg": {"size": 0,
                        "aggs": {"u": {"cardinality": {"field": "user_id"}}}},
}


def with_dept_filter(body):
    """Baseline query: same query wrapped so it only sees the visible dept."""
    b = json.loads(json.dumps(body))
    dept = {"term": {"dept": lib.VISIBLE_DEPT}}
    if "query" in b:
        b["query"] = {"bool": {"must": [b["query"]], "filter": [dept]}}
    else:
        b["query"] = dept
    return b


def gen_n(vocab, n):
    import random
    rnd = random.Random(lib.SEED + 1)
    for i in range(n):
        dept = lib.DEPARTMENTS[i % len(lib.DEPARTMENTS)]
        wc = rnd.randint(*lib.WORDS_PER_DOC)
        words = [vocab[int(rnd.random() ** 2 * lib.VOCAB_SIZE)] for _ in range(wc)]
        yield dept, {"dept": dept, "content": " ".join(words),
                     "value": rnd.randint(0, 100_000),
                     "category": f"cat-{rnd.randint(0, 49)}",
                     "user_id": f"u-{rnd.randint(0, 20_000)}",
                     "ts": 1_700_000_000_000 + i * 1000}


def load(index, gen, only_dept=None, batch=5000):
    lines, n, t0 = [], 0, time.perf_counter()
    for dept, doc in gen:
        if only_dept is not None and dept != only_dept:
            continue
        lines.append(json.dumps({"index": {"_index": index}}) + "\n")
        lines.append(json.dumps(doc) + "\n")
        n += 1
        if len(lines) >= batch * 2:
            lib.bulk(lines); lines = []
    if lines:
        lib.bulk(lines)
    lib.refresh(index)
    return n, time.perf_counter() - t0


def stable_size(index, expected_docs):
    """Read store size after flush, polling until the doc count matches and the
    reported size stops changing (forcemerge/flush settle asynchronously)."""
    lib.post(f"/{index}/_flush")
    last = -1
    for _ in range(20):
        cnt = lib.doc_count(index)
        sz = lib.index_size_bytes(index)
        if cnt == expected_docs and sz == last and sz > 0:
            return sz
        last = sz
        time.sleep(0.5)
    return lib.index_size_bytes(index)


def main():
    vocab = lib.build_vocab()
    out = {"mechanism": mechanism.NAME, "scales": []}

    for N in SCALES:
        # unique names per scale => no delete/recreate race
        SRC = f"scale-src-{N}"
        VIEW = f"scale-view-{N}" if mechanism.HAS_PHYSICAL_COPY else f"scale-alias-{N}"
        lib.delete(f"/{SRC}"); lib.delete(f"/{VIEW}")
        lib.put(f"/{SRC}", lib.MAPPING)

        n_src, t_src = load(SRC, gen_n(vocab, N))
        lib.post(f"/{SRC}/_forcemerge?max_num_segments=1&wait_for_completion=true")
        lib.refresh(SRC)

        # build the restricted view for this mechanism
        n_view, t_view, view_bytes = mechanism.create_view(
            VIEW, SRC, gen_n(vocab, N), load)

        src_bytes = stable_size(SRC, n_src)
        if mechanism.HAS_PHYSICAL_COPY:
            view_bytes = stable_size(VIEW, n_view)
        n_visible = n_view if mechanism.HAS_PHYSICAL_COPY else n_src // len(lib.DEPARTMENTS)

        rec = {
            "total_docs": n_src,
            "visible_docs": n_visible,
            "source_bytes": src_bytes,
            "view_bytes": view_bytes,
            "index_src_docs_per_sec": round(n_src / t_src, 0),
            "latency": {},
        }
        for qn, body in QUERIES.items():
            rec["latency"][qn] = {
                "baseline": lib.time_query(SRC, with_dept_filter(body),
                                           iters=150, warmup=15),
                "view": lib.time_query(VIEW, body, iters=150, warmup=15),
            }
        out["scales"].append(rec)
        print(f"N={n_src:>7d} visible={n_visible:>6d}  "
              f"src={rec['source_bytes']/1e6:>6.1f}MB view={rec['view_bytes']/1e6:>5.1f}MB  "
              f"match_bm25 base_p99={rec['latency']['match_bm25']['baseline']['p99']:.2f} "
              f"view_p99={rec['latency']['match_bm25']['view']['p99']:.2f}ms")

        # tear down this scale before building the next so only one set of
        # indices is live at a time (avoids concurrent-merge store-stats noise)
        lib.delete(f"/{SRC}"); lib.delete(f"/{VIEW}")

    with open("poc/scale_metrics.json", "w") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
