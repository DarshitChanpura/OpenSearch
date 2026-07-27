"""Setup: build the source index and the restricted view for THIS mechanism.

The mechanism (materialized view vs filtered alias) is selected by the
`mechanism.py` module on the branch. This script is identical on both branches;
diff `mechanism.py` to see how the two mechanisms differ.

Measures indexing throughput and, for a physical-copy mechanism, storage
overhead and write amplification. Emits poc/setup_metrics.json.
"""
import json
import time

import lib
import mechanism


def bulk_index(index, docs_iter, only_dept=None, batch=2000):
    """Bulk-index docs. If only_dept set, index only that dept (view refresh).
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
    metrics = {"mechanism": mechanism.NAME, "blurb": mechanism.BLURB}
    vocab = lib.build_vocab()

    # ---- clean slate --------------------------------------------------------
    for idx in (lib.SOURCE_INDEX, lib.MV_INDEX):
        lib.delete(f"/{idx}")

    # ---- 1. source index (the full, unrestricted corpus) --------------------
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

    # ---- 2. the restricted view for THIS mechanism --------------------------
    # For the materialized view this re-indexes the visible subset into a
    # separate index; for the filtered alias it just attaches a filter and
    # copies nothing. All the difference lives in mechanism.create_view.
    n_view, t_view, view_bytes = mechanism.create_view(
        mechanism.VIEW_NAME, lib.SOURCE_INDEX, lib.gen_docs(vocab), bulk_index)
    metrics["view"] = {
        "name": mechanism.VIEW_NAME,
        "has_physical_copy": mechanism.HAS_PHYSICAL_COPY,
        "docs": n_view,
        "build_seconds": round(t_view, 2),
        "docs_per_sec": round(n_view / t_view, 0) if t_view else 0,
        "store_bytes": view_bytes,
    }

    # ---- derived ------------------------------------------------------------
    src_bytes = metrics["source"]["store_bytes"]
    derived = {}
    if mechanism.HAS_PHYSICAL_COPY and n_view:
        visible_fraction = n_view / n_src
        derived = {
            "visible_fraction": round(visible_fraction, 4),
            "view_storage_overhead_pct_of_source": round(100 * view_bytes / src_bytes, 2),
            "view_vs_visible_ratio": round(view_bytes / (src_bytes * visible_fraction), 3),
            "write_amplification_with_view": round((n_src + n_view) / n_src, 3),
        }
    else:
        derived = {
            "view_storage_overhead_pct_of_source": 0.0,
            "write_amplification_with_view": 1.0,
            "note": "no physical copy; view is zero-storage and always fresh",
        }
    metrics["derived"] = derived

    with open("poc/setup_metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
