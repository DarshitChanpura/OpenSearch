"""Shared library for the access-control PoC + benchmark harness.

Runs entirely against a LOCAL OpenSearch (http://localhost:9200) started via Docker.
It never touches the production endpoint in reproduce.py / .os-creds.
"""
import json
import os
import random
import statistics
import time
import urllib.request

# Endpoint defaults to the local OpenSearch 3.7 container on :9200; override
# with OS_ENDPOINT to target another local cluster. Always local Docker;
# never the production endpoint in reproduce.py / .os-creds.
OS = os.environ.get("OS_ENDPOINT", "http://localhost:9200")

# ---- deterministic corpus config -------------------------------------------
SEED = 1337
N_DOCS = 200_000            # source corpus size
VISIBLE_DEPT = "cardiology"  # the restricted role sees only this department
DEPARTMENTS = ["cardiology", "oncology", "neurology", "radiology",
               "pediatrics", "emergency", "surgery", "psychiatry",
               "dermatology", "orthopedics"]  # cardiology ~ 1/10 = 10% visible
VOCAB_SIZE = 3000
WORDS_PER_DOC = (15, 40)
# terms that appear ONLY in hidden (non-cardiology) docs -> used by the
# local side-channel demo to show post-filter leaks and MV does not.
SECRET_TERMS = ["hunter2", "acmemerger", "infarction", "confidential",
                "quarterly", "projections", "revenue", "diagnosis"]

SOURCE_INDEX = "patients-source"
MV_INDEX = "patients-mv-cardiology"
ALIAS = "cardiology-view"


# ---- tiny HTTP helpers (stdlib only, no external deps beyond requests) ------
def _req(method, path, body=None, is_ndjson=False):
    url = OS + path
    data = None
    headers = {"Content-Type": "application/x-ndjson" if is_ndjson
               else "application/json"}
    if body is not None:
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read().decode()
    return json.loads(raw) if raw else {}


def get(path, body=None):
    return _req("GET", path, body)


def post(path, body=None):
    return _req("POST", path, body)


def put(path, body=None):
    return _req("PUT", path, body)


def delete(path):
    try:
        return _req("DELETE", path)
    except Exception:
        return {}


def bulk(ndjson_lines):
    return _req("POST", "/_bulk", "".join(ndjson_lines), is_ndjson=True)


def refresh(index):
    post(f"/{index}/_refresh")


# ---- corpus generation ------------------------------------------------------
def build_vocab():
    rnd = random.Random(SEED)
    return ["".join(rnd.choice("abcdefghijklmnopqrstuvwxyz")
                    for _ in range(rnd.randint(3, 9)))
            for _ in range(VOCAB_SIZE)]


def gen_docs(vocab):
    """Yield (dept, doc) tuples deterministically."""
    rnd = random.Random(SEED + 1)
    for i in range(N_DOCS):
        dept = DEPARTMENTS[i % len(DEPARTMENTS)]
        n = rnd.randint(*WORDS_PER_DOC)
        # Zipf-ish sampling so df varies -> realistic IDF
        words = [vocab[int(rnd.random() ** 2 * VOCAB_SIZE)] for _ in range(n)]
        # secret terms only in hidden docs
        if dept != VISIBLE_DEPT and rnd.random() < 0.15:
            words.append(rnd.choice(SECRET_TERMS))
        doc = {
            "dept": dept,
            "content": " ".join(words),
            "value": rnd.randint(0, 100_000),
            "category": f"cat-{rnd.randint(0, 49)}",
            "user_id": f"u-{rnd.randint(0, 20_000)}",
            "ts": 1_700_000_000_000 + i * 1000,
        }
        yield dept, doc


MAPPING = {
    "settings": {"number_of_shards": 1, "number_of_replicas": 0,
                 "refresh_interval": "-1"},
    "mappings": {"properties": {
        "dept": {"type": "keyword"},
        "content": {"type": "text"},
        "value": {"type": "long"},
        "category": {"type": "keyword"},
        "user_id": {"type": "keyword"},
        "ts": {"type": "date"},
    }},
}


# ---- latency measurement ----------------------------------------------------
def time_query(index, body, iters=200, warmup=20):
    """Return dict of latency stats (ms) for repeated execution of one query."""
    path = f"/{index}/_search"
    for _ in range(warmup):
        get(path, body)
    samples = []
    for _ in range(iters):
        t0 = time.perf_counter()
        get(path, body)
        samples.append((time.perf_counter() - t0) * 1000.0)
    samples.sort()
    return {
        "iters": iters,
        "p50": round(pctl(samples, 50), 3),
        "p95": round(pctl(samples, 95), 3),
        "p99": round(pctl(samples, 99), 3),
        "mean": round(statistics.mean(samples), 3),
    }


def pctl(sorted_samples, p):
    if not sorted_samples:
        return 0.0
    k = (len(sorted_samples) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sorted_samples) - 1)
    frac = k - lo
    return sorted_samples[lo] * (1 - frac) + sorted_samples[hi] * frac


def index_size_bytes(index):
    s = get(f"/{index}/_stats/store")
    return s["indices"][index]["primaries"]["store"]["size_in_bytes"]


def doc_count(index):
    c = get(f"/{index}/_count")
    return c["count"]
