"""Strict, independently annotated real-incident bucket evaluation (no tuning)."""
import argparse
import datetime as dt
import hashlib
import json
import platform
import subprocess
from pathlib import Path
from core import ALGORITHMS, COMMON_WARMUP, default, predict, score, summarize


def strict_object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError('duplicate JSON key: '+key)
        out[key] = value
    return out


def timestamp(text):
    if not isinstance(text, str):
        raise ValueError('timestamp must be a UTC string')
    parsed = dt.datetime.strptime(text, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=dt.timezone.utc)
    if parsed.second or parsed.minute % 5:
        raise ValueError('timestamp must align to a five-minute boundary')
    return parsed


def load_dataset(path):
    raw = Path(path).read_bytes()
    d = json.loads(raw, object_pairs_hook=strict_object)
    if not isinstance(d, dict):
        raise ValueError('dataset must be an object')
    if type(d.get('schema_version')) is not int or d.get('schema_version') != 1 or type(d.get('bucket_minutes')) is not int or d.get('bucket_minutes') != 5:
        raise ValueError('requires schema_version=1 and bucket_minutes=5')
    for field in ['dataset_id', 'provenance', 'annotation_method', 'annotator', 'annotation_frozen_at']:
        if not isinstance(d.get(field), str) or not d[field].strip():
            raise ValueError('missing metadata: '+field)
    # Metadata states provenance; it cannot prove annotation independence.
    dt.datetime.strptime(d['annotation_frozen_at'], '%Y-%m-%dT%H:%M:%SZ')
    if d.get('kind') != 'real-incident':
        raise ValueError('kind must explicitly be real-incident; never relabel synthetic data')
    traces = d.get('traces')
    if not isinstance(traces, list) or not traces:
        raise ValueError('nonempty traces required')
    cases, identifiers = [], set()
    for trace in traces:
        if not isinstance(trace, dict):
            raise ValueError('trace must be an object')
        identity = trace.get('id')
        if not isinstance(identity, str) or not identity.strip() or identity in identifiers:
            raise ValueError('trace ids must be unique nonempty strings')
        identifiers.add(identity)
        buckets = trace.get('buckets')
        if not isinstance(buckets, list) or not COMMON_WARMUP < len(buckets) <= 2000:
            raise ValueError('each trace requires 13..2000 continuous buckets')
        times, totals, errors = [], [], []
        for bucket in buckets:
            t = timestamp(bucket['start'])
            if times and t-times[-1] != dt.timedelta(minutes=5):
                raise ValueError('gaps/duplicates/out-of-order buckets; explicitly represent empty buckets')
            total, error = bucket['total'], bucket['errors']
            if type(total) is not int or type(error) is not int or not 0 <= error <= total <= 2147483647:
                raise ValueError('counts require 0 <= errors <= total <= Int32 limit of evaluation adapter')
            times.append(t); totals.append(total); errors.append(error)
        labels = [None]*len(times)
        coverage = trace.get('annotations')
        if not isinstance(coverage, list) or not coverage:
            raise ValueError('explicit annotation intervals required; unannotated buckets remain unknown')
        occupied = set()
        for interval in coverage:
            label = interval.get('label')
            if label not in ('normal', 'incident', 'unknown'):
                raise ValueError('annotation label must be normal/incident/unknown')
            if not isinstance(interval.get('evidence'), str) or not interval['evidence'].strip():
                raise ValueError('independent evidence reference required for each annotation')
            start, end = timestamp(interval['start']), timestamp(interval['end_exclusive'])
            if not times[0] <= start < end <= times[-1]+dt.timedelta(minutes=5):
                raise ValueError('annotation outside trace or empty')
            for i,t in enumerate(times):
                if start <= t < end:
                    # Separate occupancy tracks explicit unknown intervals too.
                    if i in occupied:
                        raise ValueError('overlapping annotation intervals')
                    occupied.add(i)
                    labels[i] = {'normal':False, 'incident':True, 'unknown':None}[label]
        if not any(x is not None for x in labels[COMMON_WARMUP:]):
            raise ValueError('no labeled buckets after common warmup')
        cases.append(dict(id=identity, errors=errors, totals=totals, labels=labels,
                          start=times[0].strftime('%Y-%m-%dT%H:%M:%SZ')))
    return d, cases, hashlib.sha256(raw).hexdigest()


def evaluate(binary, cases):
    result = {}
    for algorithm in ALGORITHMS:
        p = default(algorithm)
        records = []
        for case in cases:
            hits, trace = predict(binary, case, algorithm, p)
            records.append(dict(id=case['id'], start=case['start'],
                                score=score(case['labels'], hits), hits=hits,
                                reference_trace=trace))
        result[algorithm] = dict(parameters=p, overall=summarize([r['score'] for r in records]),
                                 traces=records)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('dataset', type=Path)
    p.add_argument('--binary', type=Path, default=Path(__file__).resolve().parents[1]/'_build/native/release/build/evaluation/adapter/adapter.exe')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        p.error('output already exists')
    d, cases, digest = load_dataset(args.dataset)
    root = Path(__file__).resolve().parents[1]
    result = dict(environment=dict(platform=platform.platform(),
                    moon=subprocess.check_output(['moon','version','--all'],text=True),
                    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
                    working_tree_dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True))),
                  source_hashes={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),root/'evaluation/core.py',root/'evaluation/adapter/main.mbt',root/'detector.mbt',root/'aggregate.mbt',root/'types.mbt']},
                  protocol='real-incident-defaults-v1', common_warmup=COMMON_WARMUP,
                  dataset_sha256=digest, dataset=d,
                  binary_sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                  warning='provenance metadata is supplied by annotators, not independently verified; no test-set tuning',
                  algorithms=evaluate(args.binary, cases))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as out:
        json.dump(result, out, indent=2);out.write('\n')


if __name__ == '__main__':
    main()
