"""Multi-scale driver: rebuild the corpus at several total sizes and, at each,
measure storage (source vs MV) and search latency for the alias (scales with
TOTAL docs) vs the MV (scales with VISIBLE docs). This gives the empirical
scaling curve used for extrapolation instead of a single point.

Visible fraction is fixed (~10%, cardiology). Emits poc/scale_metrics.json.
"""
import json
import time
import lib

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
    out = {"scales": []}

    for N in SCALES:
        # unique names per scale => no delete/recreate race
        SRC, MV, AL = f"scale-src-{N}", f"scale-mv-{N}", f"scale-view-{N}"
        lib.delete(f"/{SRC}"); lib.delete(f"/{MV}")
        lib.put(f"/{SRC}", lib.MAPPING)
        lib.put(f"/{MV}", lib.MAPPING)

        n_src, t_src = load(SRC, gen_n(vocab, N))
        lib.post(f"/{SRC}/_forcemerge?max_num_segments=1&wait_for_completion=true")
        lib.refresh(SRC)
        n_mv, t_mv = load(MV, gen_n(vocab, N), only_dept=lib.VISIBLE_DEPT)
        lib.post(f"/{MV}/_forcemerge?max_num_segments=1&wait_for_completion=true")
        lib.refresh(MV)

        lib.post("/_aliases", {"actions": [
            {"add": {"index": SRC, "alias": AL,
                     "filter": {"term": {"dept": lib.VISIBLE_DEPT}}}}]})

        src_bytes = stable_size(SRC, n_src)
        mv_bytes = stable_size(MV, n_mv)
        rec = {
            "total_docs": n_src,
            "visible_docs": n_mv,
            "source_bytes": src_bytes,
            "mv_bytes": mv_bytes,
            "index_src_docs_per_sec": round(n_src / t_src, 0),
            "index_mv_docs_per_sec": round(n_mv / t_mv, 0),
            "latency": {},
        }
        for qn, body in QUERIES.items():
            rec["latency"][qn] = {
                "alias": lib.time_query(AL, body, iters=150, warmup=15),
                "mv": lib.time_query(MV, body, iters=150, warmup=15),
            }
        out["scales"].append(rec)
        print(f"N={n_src:>7d} visible={n_mv:>6d}  "
              f"src={rec['source_bytes']/1e6:>6.1f}MB mv={rec['mv_bytes']/1e6:>5.1f}MB  "
              f"match_bm25 alias_p99={rec['latency']['match_bm25']['alias']['p99']:.2f} "
              f"mv_p99={rec['latency']['match_bm25']['mv']['p99']:.2f}ms")

        # tear down this scale before building the next so only one pair of
        # indices is live at a time (avoids concurrent-merge store-stats noise)
        lib.delete(f"/{SRC}"); lib.delete(f"/{MV}")

    with open("poc/scale_metrics.json", "w") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
