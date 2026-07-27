"""Mechanism: FILTERED ALIAS — logical post-filtering (stand-in for DLS).

The restricted view is an ALIAS over the full source index carrying a term
filter. No copy is made: queries execute against the whole shard and the filter
narrows the RESULT SET. Because BM25 collection statistics (N, df) are computed
over every document in the shard — including hidden ones — the scoring
side-channel is fully present. This is architecturally identical to the security
plugin's DLS post-filtering.

This file is the ONLY difference between the filtered-alias branch and the
materialized-view branch. Everything else in the harness is identical; diff the
two `mechanism.py` files to see exactly how the two mechanisms differ.
"""
import lib

NAME = "filtered_alias"
BLURB = "term-filtered alias over the full source index (no copy)"

# Name of the restricted view the setup script creates and queries run against.
VIEW_NAME = lib.ALIAS

# Does the view keep a physical copy (so storage/indexing overhead applies)?
HAS_PHYSICAL_COPY = False


def create_view(view_name, source_index, docs_gen, load_fn):
    """Build the restricted view for `source_index`.

    Filtered alias: attach a term-filter alias to the existing source index.
    No documents are copied. Returns (view_docs, seconds, store_bytes) with
    zero docs/seconds/bytes since nothing is indexed.
    """
    lib.post("/_aliases", {"actions": [
        {"add": {"index": source_index, "alias": view_name,
                 "filter": {"term": {"dept": lib.VISIBLE_DEPT}}}}
    ]})
    return 0, 0.0, 0


def inject_target(view_name, source_index):
    """Index the security-probe doc INTO the source index: an alias is just a
    filtered pointer at the source, so writes land there and are then read back
    through the alias — scored against full-shard statistics."""
    return source_index
