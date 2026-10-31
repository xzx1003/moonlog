"""Synthetic bucket evaluation: labels never depend on detector output."""
import hashlib
import itertools
import math
import json
import random
import statistics
import subprocess

ALGORITHMS = ('moving-average', 'ewma', 'mad')
WIDTH = 5
COMMON_WARMUP = 12  # largest window in the preregistered grid
SCENARIOS = ('normal', 'burst', 'sustained', 'traffic', 'periodic', 'low-volume')


def corpus(split):
    """Whole independent traces; no random bucket split or shared random stream."""
    if split not in ('tune', 'test'):
        raise ValueError('split must be tune or test')
    cases = []
    for scenario in SCENARIOS:
        for repetition in range(3):
            seed = (1000 if split == 'tune' else 9000) + SCENARIOS.index(scenario)*10 + repetition
            rng = random.Random(seed)
            errors = [rng.choice([1, 2, 2, 3]) for _ in range(96)]
            totals = [1000 for _ in errors]
            labels = [False for _ in errors]
            start = rng.randint(24, 36)
            length = 30 if scenario == 'sustained' else 4
            if scenario in ('burst', 'sustained', 'low-volume'):
                if scenario == 'low-volume':
                    errors = [0]*96
                    totals = [20]*96
                for i in range(start, start+length):
                    errors[i] = rng.randint(1, 2) if scenario == 'low-volume' else rng.randint(20, 30)
                    labels[i] = True
            elif scenario == 'traffic':
                # No injected fault: tenfold request/log volume, same line ratio.
                for i in range(start, start+12):
                    errors[i] *= 10
                    totals[i] *= 10
            elif scenario == 'periodic':
                for i in range(16, 96, 12):
                    errors[i] = 20  # expected scheduled job, negative target label
            # One unknown-label bucket verifies exclusion without changing time.
            labels[80] = None
            cases.append(dict(id=f'{split}-{scenario}-{repetition}', split=split,
                              scenario=scenario, seed=seed, errors=errors,
                              totals=totals, labels=labels))
    return cases


def events(labels):
    """Contiguous original positive runs; unknowns break an event."""
    result = []
    for i, label in enumerate(labels):
        if label is True:
            if result and result[-1][1] == i:
                result[-1][1] = i+1
            else:
                result.append([i, i+1])
    return result


def divide(a, b):
    return a/b if b else None


def score(labels, hits, warmup=COMMON_WARMUP):
    if len(labels) != len(hits) or warmup < 0:
        raise ValueError('invalid scoring input')
    counts = dict(tp=0, fp=0, fn=0, tn=0)
    for i, (label, hit) in enumerate(zip(labels, hits)):
        if (label is not None and not isinstance(label, bool)) or not isinstance(hit, bool):
            raise ValueError('invalid label or prediction')
        if i < warmup or label is None:
            continue
        counts['tp' if label and hit else 'fn' if label else 'fp' if hit else 'tn'] += 1
    detail = []
    for start, end in events(labels):
        if end <= warmup:
            continue
        first = next((i for i in range(max(start, warmup), end) if hits[i]), None)
        detail.append(dict(start=start, end_exclusive=end, left_censored=start < warmup,
                           detected=first is not None,
                           delay_minutes=None if first is None or start < warmup else (first-start)*WIDTH))
    return dict(**counts, events=detail)


def summarize(scores):
    c = {k:sum(s[k] for s in scores) for k in ('tp','fp','fn','tn')}
    ev = [e for s in scores for e in s['events']]
    # Left-censored events cannot have a fair onset/recall estimate.
    eligible = [e for e in ev if not e['left_censored']]
    detected = [e for e in eligible if e['detected']]
    delays = [e['delay_minutes'] for e in detected]
    return dict(**c, precision=divide(c['tp'],c['tp']+c['fp']),
                recall=divide(c['tp'],c['tp']+c['fn']),
                f1=divide(2*c['tp'],2*c['tp']+c['fp']+c['fn']),
                false_positive_rate=divide(c['fp'],c['fp']+c['tn']),
                event_count=len(eligible), detected_events=len(detected),
                missed_events=len(eligible)-len(detected),
                event_recall=divide(len(detected),len(eligible)),
                detected_delay_minutes=delays,
                median_detected_delay_minutes=statistics.median(delays) if delays else None,
                left_censored_events=len(ev)-len(eligible))


def reference(errors, algorithm, p):
    """Independent Python formula oracle, traces predictions BEFORE update."""
    n = p['window']
    ewma = sum(errors[:n])/n
    hits = [False]*len(errors)
    trace = []
    for i in range(n, len(errors)):
        previous = errors[i-n:i]
        if algorithm == 'moving-average':
            baseline = sum(previous)/n
            threshold = p['multiplier']*baseline
            high = sum(previous) == 0 or errors[i]*n > p['multiplier']*sum(previous)
        elif algorithm == 'ewma':
            baseline = ewma
            threshold = p['multiplier']*baseline
            high = errors[i] > threshold
        else:
            baseline = statistics.median(previous)
            mad = statistics.median(abs(x-baseline) for x in previous)
            threshold = baseline + p['parameter_tenths']/10*1.4826*mad
            high = errors[i] > threshold
        hits[i] = errors[i] >= p['minimum'] and high
        trace.append(dict(bucket=i, errors=errors[i], baseline=baseline,
                          threshold=threshold, hit=hits[i]))
        alpha = p['parameter_tenths']/10 if algorithm == 'ewma' else 0.3
        ewma = alpha*errors[i] + (1-alpha)*ewma
    return hits, trace


def predict(binary, case, algorithm, p):
    spikes = json.loads(subprocess.check_output([
        str(binary), algorithm, str(p['window']), str(p['multiplier']), str(p['minimum']),
        str(p['parameter_tenths']), ','.join(map(str,case['errors']))], text=True, timeout=10))
    hits = [any(a <= i*WIDTH < b for a,b,_,_ in spikes) for i in range(len(case['errors']))]
    expected, trace = reference(case['errors'], algorithm, p)
    for start,end,count,baseline in spikes:
        begin,finish=int(start)//WIDTH,int(end)//WIDTH
        if count != sum(case['errors'][begin:finish]):
            raise AssertionError('merged spike count mismatch')
        reference_baseline=next(t['baseline'] for t in trace if t['bucket']==begin)
        if not math.isclose(baseline,reference_baseline,rel_tol=1e-12,abs_tol=1e-12):
            raise AssertionError('spike reference baseline mismatch')
    if hits != expected:
        raise AssertionError((case['id'], algorithm, p, 'production/reference mismatch'))
    return hits, trace


def default(algorithm):
    return dict(window=6, multiplier=3, minimum=3,
                parameter_tenths=3 if algorithm == 'ewma' else 30)


def grid(algorithm):
    # Equal trial budget (24 each). Unused parameters held fixed.
    for window, minimum, setting in itertools.product((3,6,12),(1,3),range(4)):
        p = default(algorithm)
        p.update(window=window, minimum=minimum)
        if algorithm == 'mad': p['parameter_tenths'] = (20,30,40,60)[setting]
        elif algorithm == 'ewma': p['parameter_tenths'] = (1,3,5,8)[setting]
        else: p['multiplier'] = (2,3,4,6)[setting]
        yield p


def select(binary, tune, algorithm):
    trials = []
    for p in grid(algorithm):
        metrics = summarize([score(c['labels'], predict(binary,c,algorithm,p)[0]) for c in tune])
        trials.append(dict(parameters=p, metrics=metrics))
    # Preregistered objective: micro F1, then lower FPR; stable grid order ties.
    chosen = max(range(len(trials)), key=lambda i:(
        trials[i]['metrics']['f1'] if trials[i]['metrics']['f1'] is not None else -1,
        -(trials[i]['metrics']['false_positive_rate'] or 0)))
    return trials[chosen]['parameters'], trials


def dataset_hash(cases):
    return hashlib.sha256(json.dumps(cases,sort_keys=True,separators=(',',':')).encode()).hexdigest()
