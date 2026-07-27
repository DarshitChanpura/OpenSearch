"""Mechanism: MATERIALIZED VIEW — physical isolation.

The restricted view is a SEPARATE physical index that holds ONLY the visible
subset of documents. A refresh job re-indexes the visible docs into it. Because
hidden documents were never copied, the view has its own term dictionary and its
own collection statistics — there is no hidden `df` for the BM25 side-channel to
leak, and queries scan only the visible subset.

This file is the ONLY difference between the materialized-view branch and the
filtered-alias branch. Everything else in the harness is identical; diff the two
`mechanism.py` files to see exactly how the two mechanisms differ.
"""
import lib

NAME = "materialized_view"
BLURB = "separate physical index holding only the visible subset"

# Name of the restricted view the setup script creates and queries run against.
VIEW_NAME = lib.MV_INDEX

# Does the view keep a physical copy (so storage/indexing overhead applies)?
HAS_PHYSICAL_COPY = True


def create_view(view_name, source_index, docs_gen, load_fn):
    """Build the restricted view for `source_index`.

    Materialized view: re-index only the VISIBLE docs into a separate physical
    index, then force-merge. Returns (view_docs, seconds, store_bytes).
    """
    lib.delete(f"/{view_name}")
    lib.put(f"/{view_name}", lib.MAPPING)
    n, secs = load_fn(view_name, docs_gen, only_dept=lib.VISIBLE_DEPT)
    lib.post(f"/{view_name}/_forcemerge?max_num_segments=1&wait_for_completion=true")
    lib.refresh(view_name)
    return n, secs, lib.index_size_bytes(view_name)


def inject_target(view_name, source_index):
    """Index the security-probe doc INTO the view itself: the MV is the only
    thing the restricted role can read, and it contains only visible docs."""
    return view_name
