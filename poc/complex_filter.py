"""Demo: a COMPLEX access-control predicate honored by all three mechanisms.

Real DLS policies are rarely a single `term`. This demo uses a multi-clause
predicate and shows, live, that:

  1. a filtered alias, and
  2. a materialized view

both admit the *identical* document set the policy intends — including correct
handling of the tricky boundary cases a compound filter creates — and it
surfaces the one place they differ: freshness on a MUTABLE-field clause.

Visibility predicate:
    dept == cardiology
    OR (dept == emergency AND value < 30000)

Self-contained and re-runnable: builds its own MV + alias, then cleans up.
Requires the source index (run `python3 poc/setup.py` first). Local only.

Run:
    python3 poc/complex_filter.py
"""
import lib

MV = "patients-mv-complex"     # MV materialized from the complex predicate
ALIAS = "complex-view"         # filtered alias carrying the complex predicate
THRESH = 30000

# The compound visibility predicate a DLS role's `dls` query would carry.
FILTER = {"bool": {"should": [
    {"term": {"dept": "cardiology"}},
    {"bool": {"must": [{"term": {"dept": "emergency"}},
                       {"range": {"value": {"lt": THRESH}}}]}},
], "minimum_should_match": 1}}


def count(index, query):
    r = lib.get(f"/{index}/_search",
                {"size": 0, "track_total_hits": True, "query": query})
    return r["hits"]["total"]["value"]


def main():
    print("=" * 72)
    print(" COMPLEX FILTER  —  dept=cardiology  OR  (dept=emergency AND value<30000)")
    print("=" * 72)

    if not lib.doc_count(lib.SOURCE_INDEX):
        print(f"ERROR: {lib.SOURCE_INDEX} is empty — run `python3 poc/setup.py` first.")
        raise SystemExit(2)

    # ---- ground truth ------------------------------------------------------
    total = count(lib.SOURCE_INDEX, {"match_all": {}})
    cardio = count(lib.SOURCE_INDEX, {"term": {"dept": "cardiology"}})
    emerg_lo = count(lib.SOURCE_INDEX, {"bool": {"must": [
        {"term": {"dept": "emergency"}}, {"range": {"value": {"lt": THRESH}}}]}})
    visible = count(lib.SOURCE_INDEX, FILTER)
    print(f"\nGround truth (admin, full index of {total} docs):")
    print(f"  cardiology (all)              = {cardio}")
    print(f"  emergency AND value<{THRESH}   = {emerg_lo}")
    print(f"  admitted by complex filter    = {visible}  "
          f"(= {cardio} + {emerg_lo})")

    # ---- build the two views for the SAME predicate ------------------------
    print(f"\nBuilding materialized view '{MV}' (reindex of only admitted docs)…")
    lib.delete(f"/{MV}")
    lib.put(f"/{MV}", lib.MAPPING)
    lib.post("/_reindex?refresh&wait_for_completion=true",
             {"source": {"index": lib.SOURCE_INDEX, "query": FILTER},
              "dest": {"index": MV}})
    lib.post(f"/{MV}/_forcemerge?max_num_segments=1&wait_for_completion=true")
    lib.refresh(MV)

    print(f"Building filtered alias '{ALIAS}' carrying the complex filter…")
    lib.post("/_aliases", {"actions": [{"add": {
        "index": lib.SOURCE_INDEX, "alias": ALIAS, "filter": FILTER}}]})

    # ---- Invariant A: identical admitted set -------------------------------
    a_alias, a_mv = count(ALIAS, {"match_all": {}}), count(MV, {"match_all": {}})
    print("\n[A] Same visible document set through every mechanism")
    print(f"    complex filter (truth) = {visible}")
    print(f"    filtered alias         = {a_alias}")
    print(f"    materialized view      = {a_mv}")
    ok_a = visible == a_alias == a_mv
    print(f"    -> {'PASS' if ok_a else 'FAIL'}")

    # ---- Invariant B: boundary docs correctly excluded ---------------------
    # The hard part of a compound filter: docs that match ONE clause but not all.
    emerg_hi = {"bool": {"must": [{"term": {"dept": "emergency"}},
                                  {"range": {"value": {"gte": THRESH}}}]}}
    other = {"term": {"dept": "pediatrics"}}
    b1a, b1m = count(ALIAS, emerg_hi), count(MV, emerg_hi)
    b2a, b2m = count(ALIAS, other), count(MV, other)
    print("\n[B] Boundary docs (match one clause, fail the policy) are excluded")
    print(f"    emergency AND value>={THRESH}  -> alias={b1a}  mv={b1m}   (want 0/0)")
    print(f"    pediatrics (dept not in policy) -> alias={b2a}  mv={b2m}   (want 0/0)")
    ok_b = b1a == b1m == b2a == b2m == 0
    print(f"    -> {'PASS' if ok_b else 'FAIL'}")

    # ---- The one real difference: freshness on a MUTABLE-field clause ------
    print("\n[C] Freshness on the mutable `value` clause (the real trade-off)")
    print("    Insert an emergency doc with value=999 (<30000 => should be visible),")
    print("    then UPDATE it to value=99999 (>=30000 => should become hidden).")
    doc = {"dept": "emergency", "content": "boundary probe", "value": 999,
           "category": "cat-0", "user_id": "probe", "ts": 1_700_000_000_000}
    r = lib.post(f"/{lib.SOURCE_INDEX}/_doc?refresh=true", doc)
    pid = r["_id"]
    # the alias sees it live; the MV only sees it after a rebuild/refresh
    print(f"    after insert  -> alias sees it: {count(ALIAS, {'ids': {'values': [pid]}})}"
          f"   (MV would need a refresh to include it)")
    lib.post(f"/{lib.SOURCE_INDEX}/_update/{pid}?refresh=true", {"doc": {"value": 99999}})
    live = count(ALIAS, {"ids": {"values": [pid]}})
    print(f"    after update  -> alias sees it: {live}"
          f"   (0 = alias re-evaluated the predicate LIVE and dropped it)")
    print("    The MV, built before the update, would still be serving the stale")
    print("    admit/deny decision until its next refresh — the freshness cost of")
    print("    materialization, made visible by a mutable-field predicate.")
    lib.delete(f"/{lib.SOURCE_INDEX}/_doc/{pid}?refresh=true")

    # ---- cleanup -----------------------------------------------------------
    lib.post("/_aliases", {"actions": [{"remove": {
        "index": lib.SOURCE_INDEX, "alias": ALIAS}}]})
    lib.delete(f"/{MV}")

    print("\n" + "=" * 72)
    print(f" RESULT: doc-parity {'PASS' if ok_a else 'FAIL'} | "
          f"boundary-exclusion {'PASS' if ok_b else 'FAIL'}")
    print(" A compound predicate is honored identically by the alias and the MV.")
    print(" The alias re-evaluates it live; the MV freezes it at build/refresh time.")
    print("=" * 72)
    if not (ok_a and ok_b):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
