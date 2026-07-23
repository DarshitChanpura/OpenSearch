"""Setup: build source index, materialized view, and filtered alias.

Measures indexing throughput and write amplification. Emits poc/setup_metrics.json.
"""
import json
import time

import lib


def bulk_index(index, docs_iter, only_dept=None, batch=2000):
    """Bulk-index docs. If only_dept set, index only that dept (MV refresh sim).
    Returns (n_indexed, elapsed_seconds)."""
    lines = []
    n = 0
    t0 = time.perf_counter()
    for dept, doc in docs_iter:
        if only_dept is not None and dept != only_dept:
            continue
        lines.append(json.dumps({"index": {"_index": index}}) + "\n")
        lines.append(json.dumps(doc) + "\n")
        n += 1
        if len(lines) >= batch * 2:
            lib.bulk(lines)
            lines = []
    if lines:
        lib.bulk(lines)
    lib.refresh(index)
    return n, time.perf_counter() - t0


def main():
    metrics = {}
    vocab = lib.build_vocab()

    # ---- clean slate --------------------------------------------------------
    for idx in (lib.SOURCE_INDEX, lib.MV_INDEX):
        lib.delete(f"/{idx}")

    # ---- 1. source index (DLS / filtered-alias live here) -------------------
    lib.put(f"/{lib.SOURCE_INDEX}", lib.MAPPING)
    n_src, t_src = bulk_index(lib.SOURCE_INDEX, lib.gen_docs(vocab))
    lib.post(f"/{lib.SOURCE_INDEX}/_forcemerge?max_num_segments=1")
    lib.refresh(lib.SOURCE_INDEX)
    metrics["source"] = {
        "docs": n_src,
        "index_seconds": round(t_src, 2),
        "docs_per_sec": round(n_src / t_src, 0),
        "store_bytes": lib.index_size_bytes(lib.SOURCE_INDEX),
    }

    # ---- 2. materialized view: physical copy of VISIBLE subset only ---------
    lib.put(f"/{lib.MV_INDEX}", lib.MAPPING)
    n_mv, t_mv = bulk_index(lib.MV_INDEX, lib.gen_docs(vocab),
                            only_dept=lib.VISIBLE_DEPT)
    lib.post(f"/{lib.MV_INDEX}/_forcemerge?max_num_segments=1")
    lib.refresh(lib.MV_INDEX)
    metrics["mv"] = {
        "docs": n_mv,
        "refresh_seconds": round(t_mv, 2),
        "docs_per_sec": round(n_mv / t_mv, 0),
        "store_bytes": lib.index_size_bytes(lib.MV_INDEX),
    }

    # ---- 3. filtered alias over source (post-filter; DLS-equivalent) --------
    lib.post("/_aliases", {"actions": [
        {"add": {"index": lib.SOURCE_INDEX, "alias": lib.ALIAS,
                 "filter": {"term": {"dept": lib.VISIBLE_DEPT}}}}
    ]})
    metrics["alias"] = {
        "target": lib.SOURCE_INDEX,
        "filter": {"term": {"dept": lib.VISIBLE_DEPT}},
        "store_bytes": 0,
        "note": "zero storage; queries execute on full source index",
    }

    # ---- derived ------------------------------------------------------------
    src_bytes = metrics["source"]["store_bytes"]
    mv_bytes = metrics["mv"]["store_bytes"]
    metrics["derived"] = {
        "visible_fraction": round(n_mv / n_src, 4),
        "mv_storage_overhead_pct_of_source": round(100 * mv_bytes / src_bytes, 2),
        "mv_vs_visible_ratio": round(mv_bytes / (src_bytes * (n_mv / n_src)), 3),
        "write_amplification_with_mv": round((n_src + n_mv) / n_src, 3),
    }

    with open("poc/setup_metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
