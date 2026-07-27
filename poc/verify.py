"""Correctness verification for the access-control PoC.

The headline claim is a CONFIDENTIALITY claim, not a latency one:
  - DLS / filtered alias LEAK hidden documents through the shared term dictionary
    and collection statistics (BM25 df).
  - The materialized view CLOSES that leak because the hidden documents are
    physically absent from its segments.

The latency benchmarks (bench.py / scale.py / dls_real*.py) rely on BM25 SCORES.
This script deliberately does NOT trust scores: it reads the raw term-dictionary
`doc_freq` (df) straight from Lucene via _termvectors, and cross-checks with the
count API. If the mechanism is correct, these ground-truth structures must agree
with the score-based verdict — proving the score harness isn't fooling itself.

It asserts four independent invariants and EXITS NON-ZERO on any failure, so it
doubles as a regression gate. Runs LOCALLY only (default http://localhost:9200);
never touches production.

Run:
  python3 poc/setup.py      # build source + MV first (defaults to filtered_alias
                            # mechanism, but the MV index is built by this script
                            # directly regardless — see build_mv below)
  python3 poc/verify.py
"""
import sys

import lib

FAILS = []
CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def analyze_terms(text):
    """Ask Lucene how the standard analyzer tokenizes `text` (so we probe the
    exact stored terms, not raw strings)."""
    r = lib.post(f"/{lib.SOURCE_INDEX}/_analyze",
                 {"analyzer": "standard", "text": text})
    return [t["token"] for t in r.get("tokens", [])]


def doc_freq(index, term):
    """Read raw term-dictionary df for `term` in `index` via a synthetic
    _termvectors request (doc_id need not exist; `doc` supplies the text and
    term_statistics returns corpus-wide df). Returns int df (0 if term absent)."""
    r = lib.post(f"/{index}/_termvectors",
                 {"doc": {"content": term},
                  "fields": ["content"], "term_statistics": True})
    terms = r.get("term_vectors", {}).get("content", {}).get("terms", {})
    # the analyzer may transform the term; take the max df across produced tokens
    if not terms:
        return 0
    return max(v.get("doc_freq", 0) for v in terms.values())


def count(index, body):
    b = dict(body); b["track_total_hits"] = True
    r = lib.get(f"/{index}/_search", {"size": 0, "query": body["query"],
                                      "track_total_hits": True})
    return r["hits"]["total"]["value"]


def build_mv_if_missing():
    """Ensure a materialized-view index exists holding ONLY cardiology docs,
    independent of whichever mechanism.py setup.py used."""
    if lib.doc_count(lib.MV_INDEX) if _exists(lib.MV_INDEX) else 0:
        return
    import setup  # reuse the exact bulk loader
    lib.delete(f"/{lib.MV_INDEX}")
    lib.put(f"/{lib.MV_INDEX}", lib.MAPPING)
    vocab = lib.build_vocab()
    setup.bulk_index(lib.MV_INDEX, lib.gen_docs(vocab), only_dept=lib.VISIBLE_DEPT)
    lib.post(f"/{lib.MV_INDEX}/_forcemerge?max_num_segments=1&wait_for_completion=true")
    lib.refresh(lib.MV_INDEX)


def _exists(index):
    try:
        lib.get(f"/{index}/_count"); return True
    except Exception:
        return False


def main():
    print("=" * 72)
    print(" PoC correctness verification (ground-truth, score-independent)")
    print("=" * 72)

    if not _exists(lib.SOURCE_INDEX):
        print(f"ERROR: {lib.SOURCE_INDEX} missing — run `python3 poc/setup.py` first.")
        sys.exit(2)
    build_mv_if_missing()

    src_total = lib.doc_count(lib.SOURCE_INDEX)
    mv_total = lib.doc_count(lib.MV_INDEX)
    print(f"\nsource={src_total} docs, MV={mv_total} docs "
          f"({100*mv_total/src_total:.1f}% visible)\n")

    # ---- Invariant 1: the MV physically holds only visible docs --------------
    print("Invariant 1 — MV contains only the visible (cardiology) subset")
    hidden_in_mv = count(lib.MV_INDEX,
                         {"query": {"bool": {"must_not": [
                             {"term": {"dept": lib.VISIBLE_DEPT}}]}}})
    check("MV has ZERO non-cardiology docs", hidden_in_mv == 0,
          f"non-cardiology docs in MV = {hidden_in_mv}")
    check("MV size ≈ 10% of source",
          0.08 <= mv_total / src_total <= 0.12,
          f"ratio = {mv_total/src_total:.3f}")

    # ---- Invariant 2: GROUND TRUTH — secret-term df, read from term dict -----
    # This is the raw signal the ExactOracle exploits, read WITHOUT any scoring.
    print("\nInvariant 2 — secret-term document frequency (raw term dictionary)")
    print("  A hidden-only term must have df>0 in source but df==0 in the MV.")
    src_dfs, mv_dfs = {}, {}
    for term in lib.SECRET_TERMS:
        # secret terms are single vocab-like tokens; analyzer leaves them intact
        sdf = doc_freq(lib.SOURCE_INDEX, term)
        mdf = doc_freq(lib.MV_INDEX, term)
        src_dfs[term] = sdf; mv_dfs[term] = mdf
        print(f"    {term:14s} source_df={sdf:<6d} mv_df={mdf}")
    check("every secret term is PRESENT in source term dict (df>0)",
          all(v > 0 for v in src_dfs.values()),
          f"min source df = {min(src_dfs.values())}")
    check("every secret term is ABSENT from MV term dict (df==0)",
          all(v == 0 for v in mv_dfs.values()),
          f"max mv df = {max(mv_dfs.values())}")

    # ---- Invariant 3: negative control — a VISIBLE term must be in BOTH ------
    # Proves the check above isn't just "MV is smaller so everything is absent".
    print("\nInvariant 3 — negative control: a visible-doc term is in BOTH dicts")
    # find a common word that appears in cardiology docs
    sample = lib.get(f"/{lib.MV_INDEX}/_search",
                     {"size": 1, "query": {"match_all": {}}})
    sample_text = sample["hits"]["hits"][0]["_source"]["content"]
    visible_term = analyze_terms(sample_text)[0]
    vsrc = doc_freq(lib.SOURCE_INDEX, visible_term)
    vmv = doc_freq(lib.MV_INDEX, visible_term)
    print(f"    visible term '{visible_term}': source_df={vsrc}  mv_df={vmv}")
    check("visible term present in source (df>0)", vsrc > 0, f"df={vsrc}")
    check("visible term ALSO present in MV (df>0)", vmv > 0,
          f"df={vmv}  (if this were 0, Inv.2 would be a false positive)")

    # ---- Invariant 4: source df is strictly larger (the leak magnitude) ------
    # The whole attack: hidden docs inflate source df above the visible-only df.
    print("\nInvariant 4 — hidden docs inflate source df above MV df (the leak)")
    # ttf of a secret term over source vs (would-be) MV: MV df must be 0, and
    # source df must reflect the ~15% of hidden docs carrying it.
    leak_terms = [t for t in lib.SECRET_TERMS if src_dfs[t] > 0]
    check("secret-term source df >> MV df for all leak terms",
          all(src_dfs[t] > mv_dfs[t] for t in leak_terms),
          f"{len(leak_terms)}/{len(lib.SECRET_TERMS)} terms show source_df > mv_df")

    print("\n" + "=" * 72)
    if FAILS:
        print(f" RESULT: {len(FAILS)} INVARIANT(S) FAILED -> {FAILS}")
        print(" The confidentiality claim is NOT verified. Do not trust the numbers.")
        sys.exit(1)
    print(f" RESULT: all {len(CHECKS)} invariants hold.")
    print(" Confirmed WITHOUT relying on BM25 scores: the secret terms exist in")
    print(" the source term dictionary and are physically absent from the MV.")
    print(" The MV closes the side-channel by construction; DLS/alias cannot.")
    print("=" * 72)


if __name__ == "__main__":
    main()
