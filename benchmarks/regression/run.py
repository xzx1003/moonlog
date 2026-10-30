#!/usr/bin/env python3
"""End-to-end MoonLog CLI performance regression harness.

See benchmarks/regression/README.md for scope, protocol, and limitations.
No third-party Python dependencies; macOS and Linux only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
import threading

MIB = 1024 * 1024
BASE_SEED = 20261029
DEFAULT_SIZES = "10,100"
LARGE_THRESHOLD_MIB = 1024

BUCKET_MINUTES = 5
BUCKETS = 24 * 60 // BUCKET_MINUTES
BASELINE_BUCKETS = 6
MULTIPLIER = 3
MIN_ERRORS = 3
CONTEXT_LINES = 10
MAX_SAMPLES = 20
MAX_SIGNATURES = 1000
SCANS = 2
SPAN_START = dt.datetime(2026, 10, 28, 0, 0, tzinfo=dt.timezone.utc)
INCIDENT_BUCKETS = (12, 96, 180, 276)
INCIDENT_ERRORS_PER_1000 = 800
FATAL_EVERY = 10
DENSITIES = {"low": 1, "high": 200}
FORMATS = ("text", "jsonl")
FORMAT_INDEX = {"text": 0, "jsonl": 1}
DENSITY_INDEX = {"low": 0, "high": 1}

CHECK_NAMES = (
    "returncode_zero",
    "report_written",
    "report_json_parse",
    "report_structure",
    "source_sampling_scans",
    "summary_totals",
    "level_counts",
    "log_error_ratio",
    "time_buckets",
    "observation_buckets",
    "spikes",
    "signature_accounting",
    "context_sampling",
    "context_windows",
    "report_sha_matches_first",
    "analysis_core_matches_first",
)

MANDATORY_CORE_KEYS = (
    "summary",
    "level_counts",
    "buckets",
    "observation_buckets",
    "spikes",
    "signatures",
    "context_windows",
)

METRICS = (
    "wall_seconds",
    "user_cpu_seconds",
    "system_cpu_seconds",
    "total_cpu_seconds",
    "peak_rss_mib",
    "input_mib_per_second",
    "lines_per_second",
)

CLI_OPTIONS = [
    "analyze",
    "input.log",
    "--report",
    "report.json",
    "--format",
    "json",
    "--sampling",
    "first",
    "--detector",
    "moving-average",
    "--bucket-minutes",
    str(BUCKET_MINUTES),
    "--baseline-buckets",
    str(BASELINE_BUCKETS),
    "--multiplier",
    str(MULTIPLIER),
    "--min-errors",
    str(MIN_ERRORS),
    "--context",
    str(CONTEXT_LINES),
    "--context-mode",
    "spikes",
    "--max-samples",
    str(MAX_SAMPLES),
]

# Safe ASCII messages only: JSONL is assembled directly, without json.dumps, for
# throughput. Templates must not contain quotes, backslashes or newlines.
INFO_TEMPLATES = (
    "request completed id={seq} status=200 duration_ms={n}",
    "cache lookup id={seq} hit=true shard={n}",
    "health check ok id={seq} region={n}",
)
BASELINE_ERROR_TEMPLATES = (
    "background worker failed id={seq} attempt={n}",
    "queue retry scheduled id={seq} delay_ms={n}",
)
INCIDENT_TEMPLATES = (
    "database timeout id={seq} retry={n}",
    "connection reset id={seq} peer={n}",
    "shard unavailable id={seq} shard={n}",
    "upstream overloaded id={seq} trace={n}",
)

STAMPS = [
    (SPAN_START + dt.timedelta(minutes=m)).strftime("%Y-%m-%d %H:%M:%S")
    for m in range(BUCKETS * BUCKET_MINUTES)
]
INCIDENT_SET = frozenset(INCIDENT_BUCKETS)


class HarnessError(RuntimeError):
    pass


class ValidityError(HarnessError):
    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details


# ---------------------------------------------------------------------------
# Small JSON / value helpers
# ---------------------------------------------------------------------------


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def engine_time(minutes):
    value = SPAN_START + dt.timedelta(minutes=minutes)
    return value.strftime("%Y-%m-%d %H:%M:00Z")


def bucket_bounds(index):
    start = index * BUCKET_MINUTES
    return engine_time(start), engine_time(start + BUCKET_MINUTES)


def as_int(value):
    if isinstance(value, bool):
        raise ValueError("boolean is not an integer count")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise ValueError("non-integral number %r" % (value,))
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not re.fullmatch(r"-?\d+", text):
            raise ValueError("not an integer string: %r" % (value,))
        return int(text)
    raise ValueError("not an integer: %r" % (value,))


def as_float(value):
    if isinstance(value, bool):
        raise ValueError("boolean is not a number")
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        number = float(value)
    else:
        raise ValueError("not a number: %r" % (value,))
    if not math.isfinite(number):
        raise ValueError("non-finite number")
    return number


def utf16_length(text):
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def signature_sort_key(signature):
    """MoonBit String::compare is shortlex (UTF-16 length, then code units),
    and signatures sort by descending count before that."""
    text = signature["text"]
    return (-signature["count"], utf16_length(text), text)


def normalize_json(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: normalize_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_json(item) for item in value]
    return value


def canonical(value):
    return json.dumps(
        normalize_json(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def canonical_hash(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(8 * MIB)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def truncate(value, limit=240):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "..."


def first_difference(left, right, path="$", limit=5):
    """Return a bounded list of first differing JSON paths and values."""
    found = []

    def walk(a, b, current):
        if len(found) >= limit:
            return
        if type(a) is not type(b) and not (
            isinstance(a, (int, float))
            and not isinstance(a, bool)
            and isinstance(b, (int, float))
            and not isinstance(b, bool)
        ):
            found.append(
                {
                    "path": current,
                    "baseline": truncate(a),
                    "candidate": truncate(b),
                }
            )
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(set(a) | set(b)):
                if key not in a or key not in b:
                    found.append(
                        {
                            "path": current + "." + key,
                            "baseline": truncate(a.get(key, "<missing>")),
                            "candidate": truncate(b.get(key, "<missing>")),
                        }
                    )
                    if len(found) >= limit:
                        return
                else:
                    walk(a[key], b[key], current + "." + key)
                if len(found) >= limit:
                    return
            return
        if isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                found.append(
                    {
                        "path": current + ".length",
                        "baseline": len(a),
                        "candidate": len(b),
                    }
                )
                return
            for index, (item_a, item_b) in enumerate(zip(a, b)):
                walk(item_a, item_b, "%s[%d]" % (current, index))
                if len(found) >= limit:
                    return
            return
        if a != b:
            found.append(
                {
                    "path": current,
                    "baseline": truncate(a),
                    "candidate": truncate(b),
                }
            )

    walk(left, right, path)
    return found


def top_level_diff(left, right):
    keys = sorted(set(left) | set(right))
    return [
        key
        for key in keys
        if key not in left
        or key not in right
        or canonical(left[key]) != canonical(right[key])
    ]


def analysis_core(report):
    if not isinstance(report, dict):
        return None
    return {key: report.get(key) for key in MANDATORY_CORE_KEYS}


def report_list_length(report, key):
    if not isinstance(report, dict):
        return None
    value = report.get(key)
    return len(value) if isinstance(value, list) else None


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


def find_tool(name, extra_paths=()):
    found = shutil.which(name)
    if found:
        return found
    for candidate in extra_paths:
        path = Path(candidate).expanduser()
        if path.is_file():
            return str(path)
    return None


def tool_output(command, timeout=30):
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "%s: %s" % (type(exc).__name__, exc)
    output = (completed.stdout or "").strip()
    error = (completed.stderr or "").strip()
    if completed.returncode != 0 and not output:
        output = error
    return output or None, None


def hardware():
    cpu = None
    memory = None
    physical = None
    if sys.platform == "darwin":
        try:
            cpu = subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"], text=True
            ).strip()
        except (OSError, subprocess.SubprocessError):
            cpu = None
        try:
            memory = int(
                subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            memory = None
        try:
            physical = int(
                subprocess.check_output(["sysctl", "-n", "hw.physicalcpu"], text=True).strip()
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            physical = None
    elif sys.platform.startswith("linux"):
        try:
            text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
            for line in text.splitlines():
                if line.startswith("model name"):
                    cpu = line.split(":", 1)[1].strip()
                    break
        except OSError:
            cpu = None
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal:"):
                    memory = int(line.split()[1]) * 1024
                    break
        except (OSError, ValueError, IndexError):
            memory = None
    return {"cpu_model": cpu, "memory_bytes": memory, "physical_cpu_count": physical}


def git_info(root):
    info = {"git_commit": None, "git_branch": None, "git_dirty": None}
    try:
        info["git_commit"] = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        info["git_branch"] = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        status = subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        info["git_dirty"] = bool(status.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return info


def environment_snapshot(root, started_at):
    moon = find_tool("moon", [Path.home() / ".moon" / "bin" / "moon"])
    node = find_tool("node")
    moon_version, moon_error = (None, "moon not found")
    if moon:
        moon_version, moon_error = tool_output([moon, "version", "--all"])
    node_version, node_error = (None, "node not found")
    if node:
        node_version, node_error = tool_output([node, "--version"])
    try:
        load_start = list(os.getloadavg())
    except OSError:
        load_start = None
    env = {
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "moon_command": moon,
        "moonbit_version": moon_version,
        "moonbit_error": moon_error,
        "node_command": node,
        "node_version": node_version,
        "node_error": node_error,
        "cpu_count": os.cpu_count(),
        "load_average_start": load_start,
        "measured_at_utc": started_at,
    }
    if sys.platform == "darwin":
        env["mac_version"] = platform.mac_ver()[0]
    env.update(hardware())
    env.update(git_info(root))
    return env


# ---------------------------------------------------------------------------
# Input generation
# ---------------------------------------------------------------------------


def estimate_average_line_bytes(fmt, errors_per_1000, sequence_digits):
    stamp = "2026-10-28 12:34:00"
    sequence = "9" * max(1, sequence_digits)
    info = [t.format(seq=sequence, n=97) for t in INFO_TEMPLATES]
    errors = [t.format(seq=sequence, n=97) for t in BASELINE_ERROR_TEMPLATES]
    total = 0
    count = 5000
    for index in range(count):
        is_error = index % 1000 < errors_per_1000
        level = "FATAL" if is_error and index % FATAL_EVERY == 0 else (
            "ERROR" if is_error else "INFO"
        )
        message = errors[index % len(errors)] if is_error else info[index % len(info)]
        if fmt == "text":
            line = stamp + " [" + level + "] " + message + "\n"
        else:
            line = (
                '{"ts":"'
                + stamp
                + '","level":"'
                + level
                + '","msg":"'
                + message
                + '"}\n'
            )
        total += len(line.encode("ascii"))
    return total / count


def estimate_lines_per_bucket(target_bytes, fmt, errors_per_1000):
    digits = 6
    lines = 1
    for _ in range(6):
        average = estimate_average_line_bytes(fmt, errors_per_1000, digits)
        lines = max(1, int(target_bytes / BUCKETS / average + 0.5))
        new_digits = len(str(lines * BUCKETS))
        if new_digits == digits:
            break
        digits = new_digits
    return lines


def error_counts_for(lines_per_bucket, errors_per_1000):
    counts = []
    previous = 0
    for index in range(BUCKETS):
        cumulative = (index + 1) * lines_per_bucket * errors_per_1000 // 1000
        counts.append(cumulative - previous)
        previous = cumulative
    for index in INCIDENT_BUCKETS:
        counts[index] = lines_per_bucket * INCIDENT_ERRORS_PER_1000 // 1000
    return counts


def detect_spikes_replica(bucket_errors, lines_per_bucket):
    """Independent reimplementation of the documented moving-average rule."""
    spikes = []
    baseline_sum = 0
    for index, errors in enumerate(bucket_errors):
        if index >= BASELINE_BUCKETS:
            high = errors >= MIN_ERRORS and (
                baseline_sum == 0 or errors * BASELINE_BUCKETS > MULTIPLIER * baseline_sum
            )
            if high:
                start_minutes = index * BUCKET_MINUTES
                end_minutes = start_minutes + BUCKET_MINUTES
                if spikes and spikes[-1]["end_minutes"] == start_minutes:
                    spikes[-1]["end_minutes"] = end_minutes
                    spikes[-1]["errors"] += errors
                    spikes[-1]["peak_errors"] = max(spikes[-1]["peak_errors"], errors)
                    spikes[-1]["bucket_indices"].append(index)
                else:
                    spikes.append(
                        {
                            "start_minutes": start_minutes,
                            "end_minutes": end_minutes,
                            "errors": errors,
                            "peak_errors": errors,
                            "baseline_sum": baseline_sum,
                            "bucket_indices": [index],
                        }
                    )
            baseline_sum -= bucket_errors[index - BASELINE_BUCKETS]
        baseline_sum += errors

    result = []
    for spike in spikes:
        total_lines = len(spike["bucket_indices"]) * lines_per_bucket
        result.append(
            {
                "start": engine_time(spike["start_minutes"]),
                "end_exclusive": engine_time(spike["end_minutes"]),
                "errors": spike["errors"],
                "peak_errors": spike["peak_errors"],
                "baseline": spike["baseline_sum"] / BASELINE_BUCKETS,
                "total_lines": total_lines,
                "bucket_indices": spike["bucket_indices"],
                "log_error_ratio": {
                    "total": total_lines,
                    "errors": spike["errors"],
                    "fraction": spike["errors"] / total_lines,
                },
            }
        )
    return result


def first_error_lines(bucket_errors, lines_per_bucket, first_spike, limit):
    lines = []
    for bucket in first_spike["bucket_indices"]:
        errors = bucket_errors[bucket]
        for index in range(errors):
            position = index * lines_per_bucket // errors if errors else 0
            lines.append(bucket * lines_per_bucket + position + 1)
            if len(lines) >= limit:
                return lines
    return lines


def context_groups(target_lines, radius, total_lines):
    """Mirror ContextCollector: a target starts a new window when its context
    does not touch or overlap the current window (start > end_line + 1)."""
    groups = []
    end_line = None
    for number in target_lines:
        start = number - radius
        if end_line is None or start > end_line + 1:
            groups.append([number])
            end_line = number + radius
        else:
            groups[-1].append(number)
            end_line = max(end_line, number + radius)
    return [
        {
            "targets": group,
            "first_line": max(1, group[0] - radius),
            "last_line": min(total_lines, group[-1] + radius),
        }
        for group in groups
    ]


def build_expected(error_counts, lines_per_bucket):
    total_lines = lines_per_bucket * BUCKETS
    total_errors = sum(error_counts)
    fatal = (total_errors + FATAL_EVERY - 1) // FATAL_EVERY if total_errors else 0
    error_level = total_errors - fatal
    spikes = detect_spikes_replica(error_counts, lines_per_bucket)
    expected_spike_buckets = [tuple(spike["bucket_indices"]) for spike in spikes]
    if expected_spike_buckets != [(bucket,) for bucket in INCIDENT_BUCKETS]:
        raise HarnessError(
            "generator invariant failed: expected one spike per incident bucket, got %r"
            % (expected_spike_buckets,)
        )

    total_targets = sum(spike["errors"] for spike in spikes)
    sampled = min(MAX_SAMPLES, total_targets)
    omitted = total_targets - sampled
    first_targets = first_error_lines(
        error_counts, lines_per_bucket, spikes[0], MAX_SAMPLES
    )
    groups = context_groups(first_targets, CONTEXT_LINES, total_lines)
    window_count = len(groups)
    level_counts = {
        "DEBUG": 0,
        "INFO": total_lines - total_errors,
        "WARN": 0,
        "ERROR": error_level,
        "FATAL": fatal,
        "OTHER": 0,
    }
    expected = {
        "total": total_lines,
        "matched": total_lines,
        "untimed": 0,
        "errors": total_errors,
        "level_counts": level_counts,
        "log_error_ratio": {
            "total": total_lines,
            "errors": total_errors,
            "fraction": total_errors / total_lines,
        },
        "spike_count": len(spikes),
        "spikes": spikes,
        "sampled_targets": sampled,
        "omitted_targets": omitted,
        "omitted_global_signature_occurrences": 0,
        "bucket_count": BUCKETS,
        "lines_per_bucket": lines_per_bucket,
        "bucket_error_counts": error_counts,
        "bucket_range": {
            "start": engine_time(0),
            "end_exclusive": engine_time(BUCKETS * BUCKET_MINUTES),
        },
        "context": {
            "window_count": window_count,
            "first_target_lines": first_targets,
            "groups": groups,
            "total_targets": total_targets,
        },
        "signature_occurrences": total_errors,
        "fatal_errors": fatal,
    }
    return expected


def generate_input(path, size_mib, fmt, density, seed):
    target_bytes = size_mib * MIB
    errors_per_1000 = DENSITIES[density]
    lines_per_bucket = estimate_lines_per_bucket(target_bytes, fmt, errors_per_1000)
    error_counts = error_counts_for(lines_per_bucket, errors_per_1000)
    expected = build_expected(error_counts, lines_per_bucket)
    case_seed = (
        seed + size_mib * 1009 + FORMAT_INDEX[fmt] * 131 + DENSITY_INDEX[density] * 17
    )

    temporary = path.with_name(path.name + ".tmp")
    temporary.unlink(missing_ok=True)
    digest = hashlib.sha256()
    written = 0
    total_lines = 0
    total_errors = 0
    fatal_errors = 0
    first_targets = []
    buffer = bytearray()
    started = time.perf_counter()

    def flush(out):
        nonlocal written
        if buffer:
            out.write(buffer)
            digest.update(buffer)
            written += len(buffer)
            buffer.clear()

    try:
        with temporary.open("wb") as out:
            for bucket in range(BUCKETS):
                errors = error_counts[bucket]
                positions = (
                    [index * lines_per_bucket // errors for index in range(errors)]
                    if errors
                    else []
                )
                position_index = 0
                incident = bucket in INCIDENT_SET
                for offset in range(lines_per_bucket):
                    stamp = STAMPS[
                        bucket * BUCKET_MINUTES
                        + (offset * BUCKET_MINUTES) // lines_per_bucket
                    ]
                    is_error = (
                        position_index < errors
                        and positions[position_index] == offset
                    )
                    if is_error:
                        position_index += 1
                        level = (
                            "FATAL" if total_errors % FATAL_EVERY == 0 else "ERROR"
                        )
                        if incident:
                            template = INCIDENT_TEMPLATES[
                                total_errors % len(INCIDENT_TEMPLATES)
                            ]
                        else:
                            template = BASELINE_ERROR_TEMPLATES[
                                total_errors % len(BASELINE_ERROR_TEMPLATES)
                            ]
                        message = template.format(
                            seq=total_lines, n=(offset + bucket) % 997
                        )
                        if (
                            bucket == INCIDENT_BUCKETS[0]
                            and len(first_targets) < MAX_SAMPLES
                        ):
                            first_targets.append(
                                bucket * lines_per_bucket + offset + 1
                            )
                        total_errors += 1
                        if level == "FATAL":
                            fatal_errors += 1
                    else:
                        level = "INFO"
                        template = INFO_TEMPLATES[
                            (total_lines + case_seed) % len(INFO_TEMPLATES)
                        ]
                        message = template.format(
                            seq=total_lines, n=(offset * 7 + bucket) % 997
                        )
                    if fmt == "text":
                        line = stamp + " [" + level + "] " + message + "\n"
                    else:
                        line = (
                            '{"ts":"'
                            + stamp
                            + '","level":"'
                            + level
                            + '","msg":"'
                            + message
                            + '"}\n'
                        )
                    buffer.extend(line.encode("ascii"))
                    total_lines += 1
                    if len(buffer) >= 4 * MIB:
                        flush(out)
            flush(out)
        os.replace(str(temporary), str(path))
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    elapsed = time.perf_counter() - started
    actual_bytes = path.stat().st_size
    if actual_bytes != written:
        raise HarnessError(
            "generated size mismatch: wrote %d bytes, file has %d" % (written, actual_bytes)
        )
    if total_errors != expected["errors"]:
        raise HarnessError(
            "generated error count mismatch: %d != %d"
            % (total_errors, expected["errors"])
        )
    if fatal_errors != expected["fatal_errors"]:
        raise HarnessError(
            "generated FATAL count mismatch: %d != %d"
            % (fatal_errors, expected["fatal_errors"])
        )
    if first_targets != expected["context"]["first_target_lines"]:
        raise HarnessError("generated first target lines do not match expected analysis")

    generation = {
        "target_mib": size_mib,
        "actual_mib": actual_bytes / MIB,
        "deviation_pct": (actual_bytes - target_bytes) / target_bytes * 100.0,
        "bytes": actual_bytes,
        "lines": total_lines,
        "errors": {
            "total": total_errors,
            "ERROR": total_errors - fatal_errors,
            "FATAL": fatal_errors,
            "share": total_errors / total_lines,
        },
        "sha256": digest.hexdigest(),
        "seconds": elapsed,
        "params": {
            "seed": seed,
            "case_seed": case_seed,
            "format": fmt,
            "error_density": density,
            "baseline_errors_per_1000_lines": errors_per_1000,
            "incident_errors_per_1000_lines": INCIDENT_ERRORS_PER_1000,
            "incident_buckets": list(INCIDENT_BUCKETS),
            "fatal_every_nth_error": FATAL_EVERY,
            "span_start_utc": SPAN_START.isoformat(),
            "span_end_utc": (SPAN_START + dt.timedelta(hours=24)).isoformat(),
            "bucket_minutes": BUCKET_MINUTES,
            "bucket_count": BUCKETS,
            "lines_per_bucket": lines_per_bucket,
            "untimed_lines": 0,
            "time_distribution": "fixed 24h UTC span; lines spread across each bucket's minutes",
            "encoding": "top-level text format or JSON Lines ts/level/msg",
            "synthetic": True,
        },
    }
    return generation, expected, case_seed


def view_for(error_counts, lines_per_bucket, case_seed, fmt):
    cumulative = []
    running = 0
    for errors in error_counts:
        cumulative.append(running)
        running += errors
    return {
        "error_counts": error_counts,
        "errors_before_bucket": cumulative,
        "lines_per_bucket": lines_per_bucket,
        "case_seed": case_seed,
        "fmt": fmt,
        "total_lines": lines_per_bucket * BUCKETS,
    }


def render_line(view, index):
    """Rebuild the exact raw source line at a zero-based physical line index."""
    lines_per_bucket = view["lines_per_bucket"]
    bucket, offset = divmod(index, lines_per_bucket)
    errors = view["error_counts"][bucket]
    before = (offset * errors + lines_per_bucket - 1) // lines_per_bucket
    next_before = ((offset + 1) * errors + lines_per_bucket - 1) // lines_per_bucket
    is_error = next_before > before
    stamp = STAMPS[
        bucket * BUCKET_MINUTES
        + (offset * BUCKET_MINUTES) // lines_per_bucket
    ]
    if is_error:
        global_error = view["errors_before_bucket"][bucket] + before
        level = "FATAL" if global_error % FATAL_EVERY == 0 else "ERROR"
        if bucket in INCIDENT_SET:
            template = INCIDENT_TEMPLATES[global_error % len(INCIDENT_TEMPLATES)]
        else:
            template = BASELINE_ERROR_TEMPLATES[
                global_error % len(BASELINE_ERROR_TEMPLATES)
            ]
        message = template.format(seq=index, n=(offset + bucket) % 997)
    else:
        level = "INFO"
        template = INFO_TEMPLATES[(index + view["case_seed"]) % len(INFO_TEMPLATES)]
        message = template.format(seq=index, n=(offset * 7 + bucket) % 997)
    if view["fmt"] == "text":
        return stamp + " [" + level + "] " + message
    return (
        '{"ts":"'
        + stamp
        + '","level":"'
        + level
        + '","msg":"'
        + message
        + '"}'
    )


# ---------------------------------------------------------------------------
# Process execution
# ---------------------------------------------------------------------------


def run_process(binary, cwd, stdout_path, stderr_path, timeout=600):
    started = time.perf_counter()
    pid = os.fork()
    if pid == 0:
        try:
            os.setsid()
            os.chdir(cwd)
            os.environ["LC_ALL"] = "C"
            os.environ["TZ"] = "UTC"
            out_fd = os.open(
                str(stdout_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644
            )
            err_fd = os.open(
                str(stderr_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644
            )
            os.dup2(out_fd, 1)
            os.dup2(err_fd, 2)
            if out_fd > 2:
                os.close(out_fd)
            if err_fd > 2:
                os.close(err_fd)
            os.execv(binary, [binary] + CLI_OPTIONS)
        except BaseException:
            os._exit(127)
    timed_out = threading.Event()
    def stop_child():
        timed_out.set()
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    timer = threading.Timer(timeout, stop_child)
    timer.daemon = True
    timer.start()
    try:
        _, status, usage = os.wait4(pid, 0)
    except BaseException:
        stop_child()
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
        raise
    finally:
        timer.cancel()
        timer.join()
    if timed_out.is_set():
        raise HarnessError("CLI exceeded per-process timeout (%s seconds)" % timeout)
    elapsed = time.perf_counter() - started
    returncode = os.waitstatus_to_exitcode(status)
    if sys.platform == "darwin":
        peak_rss_mib = usage.ru_maxrss / (1024 * 1024)
    else:
        peak_rss_mib = usage.ru_maxrss / 1024
    try:
        stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        stdout = ""
    try:
        stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        stderr = ""
    return {
        "wall_seconds": elapsed,
        "user_cpu_seconds": usage.ru_utime,
        "system_cpu_seconds": usage.ru_stime,
        "peak_rss_mib": peak_rss_mib,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
    }


def execute_cli(binary, case_dir, label, timeout=600):
    report_path = case_dir / "report.json"
    report_path.unlink(missing_ok=True)
    capture_dir = case_dir / "captures"
    capture_dir.mkdir(exist_ok=True)
    stdout_path = capture_dir / (label + ".stdout")
    stderr_path = capture_dir / (label + ".stderr")
    process = run_process(binary, str(case_dir), stdout_path, stderr_path, timeout)
    report = None
    report_sha256 = None
    report_bytes = None
    report_written = report_path.is_file()
    parse_error = None
    if report_written:
        try:
            raw = report_path.read_bytes()
            report_bytes = len(raw)
            report_sha256 = hashlib.sha256(raw).hexdigest()
            report = json.loads(raw.decode("utf-8"))
            (capture_dir / (label + ".report.json")).write_bytes(raw)
        except Exception as exc:  # noqa: BLE001 - recorded as a check failure
            parse_error = "%s: %s" % (type(exc).__name__, exc)
    return {
        "process": process,
        "report": report,
        "report_sha256": report_sha256,
        "report_bytes": report_bytes,
        "report_written": report_written,
        "report_parse_error": parse_error,
    }


# ---------------------------------------------------------------------------
# Report structure and correctness checks
# ---------------------------------------------------------------------------


def check_structure(report):
    errors = []

    def require(condition, message):
        if not condition:
            errors.append(message)

    def number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    require(isinstance(report, dict), "report is not an object")
    if not isinstance(report, dict):
        return errors

    required_top = {
        "selected_signature",
        "signature_comparisons",
        "json_fields",
        "schema_version",
        "engine_version",
        "source",
        "sources",
        "sampling",
        "scans",
        "config",
        "filter",
        "time_semantics",
        "log_error_ratio_semantics",
        "summary",
        "level_counts",
        "buckets",
        "observation_buckets",
        "spikes",
        "signatures",
        "context_windows",
        "diagnostic_note",
    }
    for key in sorted(required_top - set(report)):
        errors.append("missing top-level key: " + key)
    try:
        schema_ok = as_int(report.get("schema_version", -1)) == 1
    except (TypeError, ValueError):
        schema_ok = False
    require(schema_ok, "schema_version is not 1")
    require(isinstance(report.get("engine_version"), str), "engine_version is not a string")
    require(isinstance(report.get("sources"), list), "sources is not an array")
    require(isinstance(report.get("sampling"), str), "sampling is not a string")
    require(number(report.get("scans")), "scans is not a number")
    for key in ("summary", "level_counts", "config", "filter", "json_fields"):
        require(isinstance(report.get(key), dict), key + " is not an object")
    for key in (
        "buckets",
        "observation_buckets",
        "spikes",
        "signatures",
        "context_windows",
        "signature_comparisons",
    ):
        require(isinstance(report.get(key), list), key + " is not an array")

    summary = report.get("summary")
    if isinstance(summary, dict):
        for key in (
            "total",
            "matched",
            "untimed",
            "errors",
            "spike_count",
            "sampled_targets",
            "omitted_targets",
            "omitted_global_signature_occurrences",
            "log_error_ratio",
        ):
            require(key in summary, "summary is missing " + key)
        require(isinstance(summary.get("log_error_ratio"), dict), "summary ratio is not an object")

    level_counts = report.get("level_counts")
    if isinstance(level_counts, dict):
        for level in ("DEBUG", "INFO", "WARN", "ERROR", "FATAL", "OTHER"):
            require(level in level_counts, "level_counts is missing " + level)

    buckets = report.get("buckets")
    if isinstance(buckets, list):
        for index, bucket in enumerate(buckets):
            if not isinstance(bucket, dict):
                errors.append("buckets[%d] is not an object" % index)
                break
            for key in ("start", "end_exclusive", "total", "errors"):
                if key not in bucket:
                    errors.append("buckets[%d] is missing %s" % (index, key))
            if not isinstance(bucket.get("start"), str):
                errors.append("buckets[%d].start is not a string" % index)
            if not number(bucket.get("total")):
                errors.append("buckets[%d].total is not a number" % index)
            if not number(bucket.get("errors")):
                errors.append("buckets[%d].errors is not a number" % index)
            if len(errors) > 20:
                break

    observation = report.get("observation_buckets")
    if isinstance(observation, list):
        for index, bucket in enumerate(observation):
            if not isinstance(bucket, dict):
                errors.append("observation_buckets[%d] is not an object" % index)
                break
            if not isinstance(bucket.get("start"), str):
                errors.append("observation_buckets[%d].start is not a string" % index)
            if not isinstance(bucket.get("log_error_ratio"), dict):
                errors.append(
                    "observation_buckets[%d].log_error_ratio is not an object" % index
                )
            if len(errors) > 20:
                break

    spikes = report.get("spikes")
    if isinstance(spikes, list):
        for index, spike in enumerate(spikes):
            if not isinstance(spike, dict):
                errors.append("spikes[%d] is not an object" % index)
                break
            for key in (
                "start",
                "end_exclusive",
                "errors",
                "peak_errors",
                "baseline",
                "log_error_ratio",
                "signatures",
                "omitted_signature_occurrences",
            ):
                if key not in spike:
                    errors.append("spikes[%d] is missing %s" % (index, key))
            if not isinstance(spike.get("signatures"), list):
                errors.append("spikes[%d].signatures is not an array" % index)
            if not isinstance(spike.get("log_error_ratio"), dict):
                errors.append("spikes[%d].log_error_ratio is not an object" % index)
            if len(errors) > 20:
                break

    signatures = report.get("signatures")
    if isinstance(signatures, list):
        for index, signature in enumerate(signatures):
            if not isinstance(signature, dict):
                errors.append("signatures[%d] is not an object" % index)
                break
            if not isinstance(signature.get("text"), str):
                errors.append("signatures[%d].text is not a string" % index)
            if not number(signature.get("count")):
                errors.append("signatures[%d].count is not a number" % index)
            if len(errors) > 20:
                break

    windows = report.get("context_windows")
    if isinstance(windows, list):
        for index, window in enumerate(windows):
            if not isinstance(window, dict):
                errors.append("context_windows[%d] is not an object" % index)
                break
            if not isinstance(window.get("source"), str):
                errors.append("context_windows[%d].source is not a string" % index)
            if not isinstance(window.get("targets"), list):
                errors.append("context_windows[%d].targets is not an array" % index)
            lines = window.get("lines")
            if not isinstance(lines, list):
                errors.append("context_windows[%d].lines is not an array" % index)
            else:
                for line_index, line in enumerate(lines):
                    if not isinstance(line, dict):
                        errors.append(
                            "context_windows[%d].lines[%d] is not an object"
                            % (index, line_index)
                        )
                        break
                    if not number(line.get("number")) or not isinstance(
                        line.get("text"), str
                    ):
                        errors.append(
                            "context_windows[%d].lines[%d] has invalid number/text"
                            % (index, line_index)
                        )
                        break
            if len(errors) > 20:
                break
    return errors


def ratio_state(value, expected_total, expected_errors):
    total = as_int(value["total"])
    errors = as_int(value["errors"])
    fraction = value.get("fraction")
    if total != expected_total or errors != expected_errors:
        return False, {
            "expected": {"total": expected_total, "errors": expected_errors},
            "actual": {"total": total, "errors": errors},
        }
    if total == 0:
        return fraction is None, {
            "expected_fraction": None,
            "actual_fraction": fraction,
        }
    expected_fraction = expected_errors / total
    if not isinstance(fraction, (int, float)) or isinstance(fraction, bool):
        return False, {"expected_fraction": expected_fraction, "actual_fraction": fraction}
    if abs(float(fraction) - expected_fraction) > 1e-12:
        return False, {
            "expected_fraction": expected_fraction,
            "actual_fraction": fraction,
        }
    return True, None


def validate_run(raw, expected, view):
    # The two cross-run checks are filled in after every measured run.
    checks = {
        name: name in ("report_sha_matches_first", "analysis_core_matches_first")
        for name in CHECK_NAMES
    }
    details = {}

    def mark(name, ok, detail=None):
        checks[name] = bool(ok)
        if not ok and detail is not None:
            details[name] = detail

    process = raw["process"]
    mark(
        "returncode_zero",
        process["returncode"] == 0,
        {
            "returncode": process["returncode"],
            "stderr": truncate(process["stderr"], 600),
        },
    )
    mark("report_written", raw["report_written"])
    mark(
        "report_json_parse",
        raw["report"] is not None,
        raw.get("report_parse_error"),
    )
    report = raw["report"]
    if report is None:
        return checks, details

    structural = check_structure(report)
    mark("report_structure", not structural, structural[:20] or None)

    def guarded(name, function):
        try:
            ok, detail = function()
            mark(name, ok, detail)
        except Exception as exc:  # noqa: BLE001 - a failed check is recorded
            mark(name, False, "%s: %s" % (type(exc).__name__, exc))

    def source_sampling_scans():
        mismatches = []
        if report.get("source") != "input.log":
            mismatches.append(("source", "input.log", report.get("source")))
        if report.get("sources") != ["input.log"]:
            mismatches.append(("sources", ["input.log"], report.get("sources")))
        if report.get("sampling") != "first":
            mismatches.append(("sampling", "first", report.get("sampling")))
        if as_int(report.get("scans")) != SCANS:
            mismatches.append(("scans", SCANS, report.get("scans")))
        if report.get("selected_signature") is not None:
            mismatches.append(("selected_signature", None, report.get("selected_signature")))
        if report.get("signature_comparisons") != []:
            mismatches.append(
                ("signature_comparisons", [], report.get("signature_comparisons"))
            )
        expected_fields = {"time": "ts", "level": "level", "message": "msg"}
        if report.get("json_fields") != expected_fields:
            mismatches.append(("json_fields", expected_fields, report.get("json_fields")))
        config = report.get("config") or {}
        wanted = {
            "bucket_minutes": BUCKET_MINUTES,
            "baseline_buckets": BASELINE_BUCKETS,
            "multiplier": MULTIPLIER,
            "min_errors": MIN_ERRORS,
            "context": CONTEXT_LINES,
            "context_mode": "spikes",
            "max_samples": MAX_SAMPLES,
        }
        for key, value in wanted.items():
            if config.get(key) != value:
                mismatches.append(("config." + key, value, config.get(key)))
        detector = config.get("detector", "moving-average")
        if detector != "moving-average":
            mismatches.append(("config.detector", "moving-average", detector))
        filter_value = report.get("filter") or {}
        for key, value in (
            ("level", None),
            ("keyword", ""),
            ("from_inclusive", None),
            ("to_inclusive", None),
        ):
            if filter_value.get(key) != value:
                mismatches.append(("filter." + key, value, filter_value.get(key)))
        return not mismatches, mismatches or None

    guarded("source_sampling_scans", source_sampling_scans)

    def summary_totals():
        summary = report["summary"]
        wanted = (
            ("total", expected["total"]),
            ("matched", expected["matched"]),
            ("untimed", expected["untimed"]),
            ("errors", expected["errors"]),
            ("spike_count", expected["spike_count"]),
            ("sampled_targets", expected["sampled_targets"]),
            ("omitted_targets", expected["omitted_targets"]),
            (
                "omitted_global_signature_occurrences",
                expected["omitted_global_signature_occurrences"],
            ),
        )
        mismatches = []
        for key, value in wanted:
            actual = as_int(summary[key])
            if actual != value:
                mismatches.append((key, value, actual))
        return not mismatches, mismatches or None

    guarded("summary_totals", summary_totals)

    def level_counts_check():
        counts = report["level_counts"]
        wanted = expected["level_counts"]
        mismatches = []
        for level in ("DEBUG", "INFO", "WARN", "ERROR", "FATAL", "OTHER"):
            actual = as_int(counts[level])
            if actual != wanted[level]:
                mismatches.append((level, wanted[level], actual))
        total = sum(as_int(counts[level]) for level in wanted)
        if total != expected["total"]:
            mismatches.append(("sum", expected["total"], total))
        return not mismatches, mismatches or None

    guarded("level_counts", level_counts_check)

    def log_error_ratio_check():
        ok, detail = ratio_state(
            report["summary"]["log_error_ratio"],
            expected["log_error_ratio"]["total"],
            expected["log_error_ratio"]["errors"],
        )
        return ok, detail

    guarded("log_error_ratio", log_error_ratio_check)

    def bucket_check(collection_name, include_ratio):
        buckets = report[collection_name]
        if not isinstance(buckets, list):
            return False, {"error": collection_name + " is not an array"}
        if len(buckets) != expected["bucket_count"]:
            return False, {
                "expected_count": expected["bucket_count"],
                "actual_count": len(buckets),
            }
        mismatches = 0
        first = None
        totals = 0
        errors_sum = 0
        for index, bucket in enumerate(buckets):
            if not isinstance(bucket, dict):
                mismatches += 1
                if first is None:
                    first = {"index": index, "field": "object", "actual": bucket}
                continue
            start, end = bucket_bounds(index)
            fields = [
                ("start", start, bucket.get("start")),
                ("end_exclusive", end, bucket.get("end_exclusive")),
            ]
            if include_ratio:
                ratio = bucket.get("log_error_ratio")
                if not isinstance(ratio, dict):
                    mismatches += 1
                    if first is None:
                        first = {"index": index, "field": "log_error_ratio", "actual": ratio}
                    continue
                try:
                    ratio_total = as_int(ratio.get("total"))
                    ratio_errors = as_int(ratio.get("errors"))
                except (TypeError, ValueError) as exc:
                    mismatches += 1
                    if first is None:
                        first = {
                            "index": index,
                            "field": "ratio.counts",
                            "detail": "%s: %s" % (type(exc).__name__, exc),
                        }
                    continue
                fields.extend(
                    [
                        ("ratio.total", expected["lines_per_bucket"], ratio_total),
                        (
                            "ratio.errors",
                            expected["bucket_error_counts"][index],
                            ratio_errors,
                        ),
                    ]
                )
                try:
                    ratio_ok, ratio_detail = ratio_state(
                        ratio,
                        expected["lines_per_bucket"],
                        expected["bucket_error_counts"][index],
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    ratio_ok, ratio_detail = False, "%s: %s" % (
                        type(exc).__name__,
                        exc,
                    )
                if not ratio_ok:
                    mismatches += 1
                    if first is None:
                        first = {
                            "index": index,
                            "field": "log_error_ratio",
                            "detail": ratio_detail,
                        }
                try:
                    totals += as_int(ratio.get("total"))
                    errors_sum += as_int(ratio.get("errors"))
                except (TypeError, ValueError):
                    pass
            else:
                try:
                    bucket_total = as_int(bucket.get("total"))
                    bucket_errors = as_int(bucket.get("errors"))
                except (TypeError, ValueError) as exc:
                    mismatches += 1
                    if first is None:
                        first = {
                            "index": index,
                            "field": "bucket.counts",
                            "detail": "%s: %s" % (type(exc).__name__, exc),
                        }
                    continue
                fields.extend(
                    [
                        ("total", expected["lines_per_bucket"], bucket_total),
                        (
                            "errors",
                            expected["bucket_error_counts"][index],
                            bucket_errors,
                        ),
                    ]
                )
                totals += bucket_total
                errors_sum += bucket_errors
            for field, wanted, actual in fields:
                if wanted != actual:
                    mismatches += 1
                    if first is None:
                        first = {
                            "index": index,
                            "field": field,
                            "expected": wanted,
                            "actual": actual,
                        }
        if totals != expected["total"]:
            mismatches += 1
            if first is None:
                first = {
                    "field": "sum.total",
                    "expected": expected["total"],
                    "actual": totals,
                }
        if errors_sum != expected["errors"]:
            mismatches += 1
            if first is None:
                first = {
                    "field": "sum.errors",
                    "expected": expected["errors"],
                    "actual": errors_sum,
                }
        return mismatches == 0, (
            None if mismatches == 0 else {"mismatches": mismatches, "first": first}
        )

    guarded("time_buckets", lambda: bucket_check("buckets", False))
    guarded("observation_buckets", lambda: bucket_check("observation_buckets", True))

    def spikes_check():
        spikes = report["spikes"]
        wanted = expected["spikes"]
        if len(spikes) != len(wanted):
            return False, {"expected_count": len(wanted), "actual_count": len(spikes)}
        mismatches = []
        for index, (actual, target) in enumerate(zip(spikes, wanted)):
            if actual.get("start") != target["start"]:
                mismatches.append((index, "start", target["start"], actual.get("start")))
            if actual.get("end_exclusive") != target["end_exclusive"]:
                mismatches.append(
                    (
                        index,
                        "end_exclusive",
                        target["end_exclusive"],
                        actual.get("end_exclusive"),
                    )
                )
            for key in ("errors", "peak_errors"):
                value = as_int(actual.get(key))
                if value != target[key]:
                    mismatches.append((index, key, target[key], value))
            try:
                baseline = as_float(actual.get("baseline"))
            except (TypeError, ValueError):
                baseline = None
            if baseline is None or abs(baseline - target["baseline"]) > 1e-9:
                mismatches.append((index, "baseline", target["baseline"], baseline))
            ratio_ok, ratio_detail = ratio_state(
                actual.get("log_error_ratio") or {},
                target["log_error_ratio"]["total"],
                target["log_error_ratio"]["errors"],
            )
            if not ratio_ok:
                mismatches.append((index, "log_error_ratio", ratio_detail, None))
            omitted = as_int(actual.get("omitted_signature_occurrences", 0))
            if omitted != 0:
                mismatches.append((index, "omitted_signature_occurrences", 0, omitted))
            signatures = actual.get("signatures")
            if not isinstance(signatures, list) or not signatures:
                mismatches.append((index, "signatures", "nonempty array", signatures))
                continue
            counts = 0
            keys = []
            for signature in signatures:
                count = as_int(signature.get("count"))
                text = signature.get("text")
                if not isinstance(text, str) or not text:
                    mismatches.append((index, "signature.text", "nonempty string", text))
                    continue
                counts += count
                keys.append(signature_sort_key({"text": text, "count": count}))
            if keys != sorted(keys):
                mismatches.append(
                    (index, "signatures.order", "count desc, shortlex text asc", None)
                )
            if counts + omitted != target["errors"]:
                mismatches.append(
                    (
                        index,
                        "signature_sum",
                        target["errors"],
                        counts + omitted,
                    )
                )
        return not mismatches, mismatches[:10] or None

    guarded("spikes", spikes_check)

    def signature_accounting():
        signatures = report["signatures"]
        total = 0
        keys = []
        for signature in signatures:
            text = signature.get("text")
            if not isinstance(text, str) or not text:
                return False, {"bad_text": text}
            count = as_int(signature.get("count"))
            if count <= 0:
                return False, {"bad_count": count, "text": text}
            total += count
            keys.append(signature_sort_key({"text": text, "count": count}))
        if keys != sorted(keys):
            return False, {
                "error": "signatures are not ordered by count desc, shortlex text asc"
            }
        overflow = as_int(expected["omitted_global_signature_occurrences"])
        if total + overflow != expected["errors"]:
            return False, {
                "expected": expected["errors"],
                "signature_sum": total,
                "overflow": overflow,
            }
        return True, None

    guarded("signature_accounting", signature_accounting)

    def context_sampling():
        summary = report["summary"]
        sampled = as_int(summary["sampled_targets"])
        omitted = as_int(summary["omitted_targets"])
        windows = report["context_windows"]
        mismatches = []
        if sampled != expected["sampled_targets"]:
            mismatches.append(("sampled_targets", expected["sampled_targets"], sampled))
        if omitted != expected["omitted_targets"]:
            mismatches.append(("omitted_targets", expected["omitted_targets"], omitted))
        if len(windows) != expected["context"]["window_count"]:
            mismatches.append(
                (
                    "window_count",
                    expected["context"]["window_count"],
                    len(windows),
                )
            )
        actual_targets = []
        for window in windows:
            actual_targets.extend(as_int(item) for item in window.get("targets", []))
        if actual_targets != expected["context"]["first_target_lines"]:
            mismatches.append(
                (
                    "sampled_target_lines",
                    expected["context"]["first_target_lines"][:20],
                    actual_targets[:20],
                )
            )
        return not mismatches, mismatches or None

    guarded("context_sampling", context_sampling)

    def context_windows_check():
        windows = report["context_windows"]
        if not isinstance(windows, list) or not windows:
            return False, {"error": "no context windows"}
        groups = expected["context"]["groups"]
        mismatches = []
        if len(windows) != len(groups):
            mismatches.append(
                ("window_count", len(groups), len(windows))
            )
        for index, window in enumerate(windows):
            if window.get("source") != "input.log":
                mismatches.append((index, "source", "input.log", window.get("source")))
            targets = [as_int(item) for item in window.get("targets", [])]
            if targets != sorted(set(targets)):
                mismatches.append((index, "targets.order", "sorted unique", targets))
            lines = window.get("lines", [])
            numbers = []
            seen = set()
            for line in lines:
                number = as_int(line.get("number"))
                text = line.get("text")
                if not isinstance(text, str):
                    mismatches.append((index, "line.text", "string", text))
                    continue
                if number in seen:
                    mismatches.append((index, "line.number", "unique", number))
                seen.add(number)
                numbers.append(number)
                if number < 1 or number > expected["total"]:
                    mismatches.append((index, "line.number.range", expected["total"], number))
                    continue
                expected_text = render_line(view, number - 1)
                if text != expected_text:
                    mismatches.append(
                        (
                            index,
                            "line.text",
                            truncate(expected_text),
                            truncate(text),
                        )
                    )
            if not numbers:
                mismatches.append((index, "lines", "nonempty", 0))
                continue
            if numbers != sorted(numbers):
                mismatches.append((index, "lines.order", "ascending", numbers[:10]))
            if index < len(groups):
                group = groups[index]
                if targets != group["targets"]:
                    mismatches.append(
                        (index, "targets", group["targets"], targets)
                    )
                expected_numbers = list(
                    range(group["first_line"], group["last_line"] + 1)
                )
                if numbers != expected_numbers:
                    mismatches.append(
                        (
                            index,
                            "line_range",
                            [expected_numbers[0], expected_numbers[-1]],
                            [numbers[0], numbers[-1]] if numbers else [],
                        )
                    )
            missing = [target for target in targets if target not in seen]
            if missing:
                mismatches.append((index, "targets.missing", "targets in lines", missing[:10]))
        return not mismatches, mismatches[:10] or None

    guarded("context_windows", context_windows_check)
    return checks, details


# ---------------------------------------------------------------------------
# Statistics and version comparison
# ---------------------------------------------------------------------------


def summarize(values):
    count = len(values)
    if count == 0:
        return {
            "count": 0,
            "median": None,
            "min": None,
            "max": None,
            "mean": None,
            "p95": None,
        }
    ordered = sorted(values)
    p95 = None
    if count >= 20:
        p95 = ordered[max(0, math.ceil(0.95 * count) - 1)]
    return {
        "count": count,
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / count,
        "p95": p95,
    }


def change_pct(candidate, baseline):
    if candidate is None or baseline is None or baseline == 0:
        return None
    return (candidate - baseline) / baseline * 100.0


def version_statistics(samples):
    return {
        metric: summarize([float(sample[metric]) for sample in samples])
        for metric in METRICS
    }


def paired_changes(baseline_samples, candidate_samples):
    baseline_by_iteration = {
        sample["iteration"]: sample for sample in baseline_samples
    }
    candidate_by_iteration = {
        sample["iteration"]: sample for sample in candidate_samples
    }
    iterations = sorted(set(baseline_by_iteration) & set(candidate_by_iteration))
    if not iterations:
        return None
    out = {"iterations": len(iterations)}
    for metric in ("wall_seconds", "peak_rss_mib", "input_mib_per_second"):
        values = []
        for iteration in iterations:
            base = baseline_by_iteration[iteration][metric]
            cand = candidate_by_iteration[iteration][metric]
            change = change_pct(cand, base)
            if change is not None:
                values.append(change)
        out[metric + "_median_pct"] = statistics.median(values) if values else None
    return out


def compare_reports(
    baseline_report,
    candidate_report,
    baseline_sha,
    candidate_sha,
    allow_diff,
    allow_format,
):
    differing = top_level_diff(baseline_report, candidate_report)
    mandatory_diff = [key for key in differing if key in MANDATORY_CORE_KEYS]
    allowed_set = set(allow_diff)
    disallowed = [key for key in differing if key not in allowed_set]
    stripped_equal = canonical(
        {key: value for key, value in baseline_report.items() if key not in allowed_set}
    ) == canonical(
        {key: value for key, value in candidate_report.items() if key not in allowed_set}
    )
    raw_equal = baseline_sha is not None and baseline_sha == candidate_sha
    if raw_equal:
        consistent = True
    elif not differing:
        # Parsed content is identical; only bytes (key order, whitespace,
        # escaping) differ, which requires the explicit format allowance.
        consistent = bool(allow_format)
    else:
        consistent = not disallowed and stripped_equal and not mandatory_diff
    return {
        "baseline_report_sha256": baseline_sha,
        "candidate_report_sha256": candidate_sha,
        "report_bytes_equal": raw_equal,
        "differing_top_level_keys": differing,
        "allowed_diff_keys": list(allow_diff),
        "disallowed_diff_keys": disallowed,
        "allow_report_format": bool(allow_format),
        "mandatory_core_diff_keys": mandatory_diff,
        "stripped_report_semantics_equal": stripped_equal,
        "consistent": bool(consistent),
        "diff_details": first_difference(
            {key: baseline_report.get(key) for key in disallowed},
            {key: candidate_report.get(key) for key in disallowed},
        )
        if disallowed
        else [],
    }


# ---------------------------------------------------------------------------
# Case runner
# ---------------------------------------------------------------------------


def sample_metrics(process, generation):
    wall = process["wall_seconds"]
    return {
        "wall_seconds": wall,
        "user_cpu_seconds": process["user_cpu_seconds"],
        "system_cpu_seconds": process["system_cpu_seconds"],
        "total_cpu_seconds": process["user_cpu_seconds"] + process["system_cpu_seconds"],
        "peak_rss_mib": process["peak_rss_mib"],
        "input_mib_per_second": generation["bytes"] / MIB / wall if wall > 0 else None,
        "lines_per_second": generation["lines"] / wall if wall > 0 else None,
    }


def sample_from_raw(raw, version, iteration, order, generation, expected, view):
    report = raw["report"]
    metrics = sample_metrics(raw["process"], generation)
    core = analysis_core(report)
    checks, details = validate_run(raw, expected, view)
    sample = {
        "version": version,
        "iteration": iteration,
        "order": order,
        "allocations": "unsupported",
        **metrics,
        "returncode": raw["process"]["returncode"],
        "stdout": raw["process"]["stdout"],
        "stderr": raw["process"]["stderr"],
        "report_sha256": raw["report_sha256"],
        "report_bytes": raw["report_bytes"],
        "report_summary": report.get("summary") if isinstance(report, dict) else None,
        "level_counts": report.get("level_counts") if isinstance(report, dict) else None,
        "spike_count": report_list_length(report, "spikes"),
        "context_window_count": report_list_length(report, "context_windows"),
        "bucket_count": report_list_length(report, "buckets"),
        "analysis_core_sha256": canonical_hash(core) if core is not None else None,
        "checks": checks,
        "checks_passed": all(checks.values()),
    }
    if details:
        sample["check_details"] = details
    return sample


def warmup_from_sample(sample):
    return {
        "wall_seconds": sample["wall_seconds"],
        "returncode": sample["returncode"],
        "report_sha256": sample["report_sha256"],
        "analysis_core_sha256": sample["analysis_core_sha256"],
        "report_summary": sample["report_summary"],
        "checks_passed": sample["checks_passed"],
    }


def failed_checks(sample):
    return [name for name, ok in sample["checks"].items() if not ok]


def run_case(case_spec, binaries, args, work_root, result):
    size_mib, fmt, density = case_spec
    name = "%dMiB-%s-%s" % (size_mib, fmt, density)
    case_dir = work_root / name
    case_dir.mkdir()
    target_bytes = size_mib * MIB
    required = int(target_bytes * 1.2) + 256 * MIB
    free = shutil.disk_usage(str(work_root)).free
    if free < required:
        raise HarnessError(
            "%s: insufficient free space: need about %.1f MiB, have %.1f MiB"
            % (name, required / MIB, free / MIB)
        )
    input_path = case_dir / "input.log"
    print(
        "%s: generating %.0f MiB %s %s input ..." % (name, size_mib, fmt, density),
        flush=True,
    )
    generation, expected, case_seed = generate_input(
        input_path, size_mib, fmt, density, args.seed
    )
    view = view_for(
        expected["bucket_error_counts"],
        expected["lines_per_bucket"],
        case_seed,
        fmt,
    )
    case = {
        "name": name,
        "nominal_mib": size_mib,
        "format": fmt,
        "error_density": density,
        "generation": generation,
        "expected": expected,
        "warmup": {},
        "samples": [],
        "statistics": None,
        "verification": None,
    }
    result["cases"].append(case)
    print(
        "%s: %.3f MiB, %d lines, %d errors, sha256 %s"
        % (
            name,
            generation["actual_mib"],
            generation["lines"],
            generation["errors"]["total"],
            generation["sha256"],
        ),
        flush=True,
    )

    versions = []
    if binaries.get("baseline"):
        versions.append("baseline")
    versions.append("candidate")

    for warmup_index in range(args.warmups):
        warmup_order = (
            list(versions)
            if warmup_index % 2 == 0 or len(versions) == 1
            else list(reversed(versions))
        )
        for version in warmup_order:
            label = "%s-warmup-%d" % (version, warmup_index + 1)
            raw = execute_cli(binaries[version], case_dir, label, args.timeout)
            full_sample = sample_from_raw(
                raw, version, 0, 0, generation, expected, view
            )
            warmup = warmup_from_sample(full_sample)
            case["warmup"].setdefault(version, []).append(warmup)
            if not warmup["checks_passed"]:
                result["checks"]["per_run_validity"] = False
                result["checks"]["expected_analysis_matched"] = False
                raise ValidityError(
                    "%s: warmup %d failed for %s" % (name, warmup_index + 1, version),
                    {
                        "version": version,
                        "warmup": warmup,
                        "failed_checks": failed_checks(full_sample),
                        "check_details": full_sample.get("check_details", {}),
                        "stdout": truncate(raw["process"]["stdout"], 1200),
                        "stderr": truncate(raw["process"]["stderr"], 1200),
                    },
                )
            print(
                "%s: warmup %d %s %.3fs"
                % (name, warmup_index + 1, version, warmup["wall_seconds"]),
                flush=True,
            )

    first_reports = {}
    for iteration in range(1, args.runs + 1):
        order = (
            list(versions)
            if len(versions) == 1 or iteration % 2 == 1
            else list(reversed(versions))
        )
        for position, version in enumerate(order, start=1):
            label = "%s-%d" % (version, iteration)
            raw = execute_cli(binaries[version], case_dir, label, args.timeout)
            sample = sample_from_raw(
                raw, version, iteration, position, generation, expected, view
            )
            case["samples"].append(sample)
            if sample["checks_passed"]:
                if version not in first_reports:
                    first_reports[version] = raw["report"]
            else:
                failed = failed_checks(sample)
                result["checks"]["per_run_validity"] = False
                result["checks"]["expected_analysis_matched"] = False
                raise ValidityError(
                    "%s: %s iteration %d failed checks: %s"
                    % (name, version, iteration, ", ".join(failed)),
                    {
                        "version": version,
                        "iteration": iteration,
                        "failed_checks": failed,
                        "check_details": sample.get("check_details", {}),
                        "stdout": truncate(sample["stdout"], 1200),
                        "stderr": truncate(sample["stderr"], 1200),
                    },
                )
        base = next(
            (
                s
                for s in case["samples"]
                if s["version"] == "baseline" and s["iteration"] == iteration
            ),
            None,
        )
        cand = next(
            (
                s
                for s in case["samples"]
                if s["version"] == "candidate" and s["iteration"] == iteration
            ),
            None,
        )
        if base and cand:
            print(
                "%s: iteration %d baseline %.3fs / candidate %.3fs"
                % (name, iteration, base["wall_seconds"], cand["wall_seconds"]),
                flush=True,
            )
        else:
            print(
                "%s: iteration %d %s %.3fs"
                % (name, iteration, cand["version"] if cand else "?", cand["wall_seconds"] if cand else 0.0),
                flush=True,
            )

    by_version = {
        version: [s for s in case["samples"] if s["version"] == version]
        for version in versions
    }
    statistics_by_version = {
        version: version_statistics(samples) for version, samples in by_version.items()
    }
    change = None
    paired = None
    if "baseline" in by_version:
        change = {}
        for metric in (
            "wall_seconds",
            "peak_rss_mib",
            "input_mib_per_second",
            "total_cpu_seconds",
        ):
            change[metric + "_median_pct"] = change_pct(
                statistics_by_version["candidate"][metric]["median"],
                statistics_by_version["baseline"][metric]["median"],
            )
        paired = paired_changes(by_version["baseline"], by_version["candidate"])
    case["statistics"] = {
        "baseline": statistics_by_version.get("baseline"),
        "candidate": statistics_by_version["candidate"],
        "change_pct": change,
        "paired_change_pct": paired,
    }

    sha_stable = {}
    core_stable = {}
    for version in versions:
        samples = by_version[version]
        shas = [sample["report_sha256"] for sample in samples]
        cores = [sample["analysis_core_sha256"] for sample in samples]
        for warmup in case["warmup"].get(version, []):
            shas.append(warmup["report_sha256"])
            cores.append(warmup["analysis_core_sha256"])
        sha_stable[version] = (
            all(value is not None for value in shas) and len(set(shas)) == 1
        )
        core_stable[version] = (
            all(value is not None for value in cores) and len(set(cores)) == 1
        )
        first_sha = samples[0]["report_sha256"]
        first_core = samples[0]["analysis_core_sha256"]
        for sample in samples:
            sample["checks"]["report_sha_matches_first"] = (
                sample["report_sha256"] == first_sha
            )
            sample["checks"]["analysis_core_matches_first"] = (
                sample["analysis_core_sha256"] == first_core
            )
            sample["checks_passed"] = all(sample["checks"].values())

    cross_version = None
    if "baseline" in versions:
        cross_version = compare_reports(
            first_reports["baseline"],
            first_reports["candidate"],
            by_version["baseline"][0]["report_sha256"],
            by_version["candidate"][0]["report_sha256"],
            args.allow_report_diff,
            args.allow_report_format,
        )
        if not cross_version["consistent"]:
            result["checks"]["cross_version_consistent"] = False

    expected_matched = all(
        all(ok for name, ok in sample["checks"].items() if name not in (
            "report_sha_matches_first",
            "analysis_core_matches_first",
        ))
        for sample in case["samples"]
    )
    all_valid = all(
        sample["checks_passed"] for sample in case["samples"]
    ) and all(
        warmup["checks_passed"]
        for warmups in case["warmup"].values()
        for warmup in warmups
    )
    case["verification"] = {
        "samples_checked": len(case["samples"]),
        "warmups_checked": sum(
            len(warmups) for warmups in case["warmup"].values()
        ),
        "all_samples_valid": all_valid,
        "expected_analysis_matched": expected_matched,
        "report_sha_stable": sha_stable,
        "analysis_core_stable": core_stable,
        "warmup_report_sha_matches_samples": {
            version: all(
                warmup["report_sha256"]
                == by_version[version][0]["report_sha256"]
                for warmup in case["warmup"].get(version, [])
            )
            for version in versions
        },
        "cross_version": cross_version,
    }
    if not all_valid or not all(sha_stable.values()) or not all(core_stable.values()):
        result["checks"]["per_run_validity"] = False
        if not all(sha_stable.values()):
            result["checks"]["within_version_sha_reproducible"] = False
        if not all(core_stable.values()):
            result["checks"]["within_version_analysis_stable"] = False
        raise ValidityError(
            "%s: report reproducibility check failed" % name,
            {
                "report_sha_stable": sha_stable,
                "analysis_core_stable": core_stable,
                "samples": len(case["samples"]),
            },
        )
    if not expected_matched:
        result["checks"]["expected_analysis_matched"] = False
        raise ValidityError("%s: expected analysis check failed" % name)

    if cross_version is not None and not cross_version["consistent"]:
        print(
            "%s: WARNING: baseline and candidate reports are inconsistent"
            % name,
            flush=True,
        )

    if not args.keep_work:
        shutil.rmtree(case_dir, ignore_errors=True)

    stats = case["statistics"]
    baseline_median = (
        stats["baseline"]["wall_seconds"]["median"] if stats["baseline"] else None
    )
    candidate_median = stats["candidate"]["wall_seconds"]["median"]
    if baseline_median is None:
        print(
            "%s: candidate median %.3fs, %.1f MiB/s"
            % (
                name,
                candidate_median,
                stats["candidate"]["input_mib_per_second"]["median"],
            ),
            flush=True,
        )
    else:
        print(
            "%s: wall %.3fs -> %.3fs (%+.1f%%), RSS %.1f -> %.1f MiB (%+.1f%%), %s"
            % (
                name,
                baseline_median,
                candidate_median,
                change["wall_seconds_median_pct"],
                stats["baseline"]["peak_rss_mib"]["median"],
                stats["candidate"]["peak_rss_mib"]["median"],
                change["peak_rss_mib_median_pct"],
                "outputs consistent"
                if cross_version and cross_version["consistent"]
                else "outputs differ",
            ),
            flush=True,
        )
    return case


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def fmt_number(value, digits=3):
    if value is None:
        return "N/A"
    return ("%." + str(digits) + "f") % value


def fmt_pct(value):
    if value is None:
        return "N/A"
    return "%+.1f%%" % value


def one_line(value, limit=400):
    if not value:
        return "unknown"
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[:limit] + "..."


def markdown_summary(result):
    lines = ["# MoonLog CLI performance regression", ""]
    lines.append(
        "End-to-end native CLI: process startup, two scans, SHA-256 consistency, parsing, "
        "time buckets, spike detection, context sampling, JSON report write and terminal summary."
    )
    lines.append("")
    env = result.get("environment", {})
    lines.append("## Environment")
    lines.append("")
    lines.append("- Git commit: `%s`%s" % (
        one_line(env.get("git_commit")),
        " (dirty)" if env.get("git_dirty") else "",
    ))
    lines.append("- MoonBit: `%s`" % one_line(env.get("moonbit_version")))
    lines.append("- Node: `%s`" % one_line(env.get("node_version")))
    lines.append(
        "- OS / arch: %s / %s"
        % (one_line(env.get("platform")), one_line(env.get("machine")))
    )
    lines.append("- CPU: %s (%s logical)" % (
        one_line(env.get("cpu_model")),
        env.get("cpu_count"),
    ))
    memory = env.get("memory_bytes")
    lines.append(
        "- Memory: %s"
        % (("%.1f GiB" % (memory / (1024 ** 3))) if memory else "unknown")
    )
    lines.append("- Measured at: %s" % one_line(env.get("measured_at_utc")))
    lines.append("")
    params = result.get("parameters", {})
    lines.append("## Parameters")
    lines.append("")
    lines.append("- Seed: %s; sizes MiB: %s; warmups: %s; runs: %s; interleaved: %s" % (
        params.get("seed"),
        params.get("sizes_mib"),
        params.get("warmups"),
        params.get("runs"),
        params.get("interleaved"),
    ))
    lines.append(
        "- Allocations: `unsupported`; peak RSS is the child OS high-water mark, not allocations."
    )
    lines.append(
        "- Gates: %s; wall > %.1f%%, RSS > %.1f%%, output consistency"
        % (
            "enabled" if params.get("gate", {}).get("enabled") else "disabled (report only)",
            params.get("gate", {}).get("wall_pct", 15.0),
            params.get("gate", {}).get("rss_pct", 20.0),
        )
    )
    lines.append("")
    lines.append("## Cases")
    lines.append("")
    if result.get("cases"):
        lines.append(
            "| Case | Input MiB | Lines | Errors | Baseline s | Candidate s | Δ wall | Baseline RSS MiB | Candidate RSS MiB | Δ RSS | Candidate MiB/s | Outputs |"
        )
        lines.append(
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"
        )
        for case in result["cases"]:
            gen = case.get("generation", {})
            stats = case.get("statistics")
            verification = case.get("verification") or {}
            cross = verification.get("cross_version")
            outputs = (
                "consistent"
                if cross and cross.get("consistent")
                else ("differ" if cross else "single version")
            )
            if not stats:
                lines.append(
                    "| %s | %.2f | %s | %s | — | — | — | — | — | — | — | %s |"
                    % (
                        case.get("name"),
                        gen.get("actual_mib", 0.0),
                        gen.get("lines", "?"),
                        gen.get("errors", {}).get("total", "?"),
                        outputs,
                    )
                )
                continue
            base = stats.get("baseline")
            cand = stats["candidate"]
            change = stats.get("change_pct") or {}
            lines.append(
                "| %s | %.2f | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |"
                % (
                    case.get("name"),
                    gen.get("actual_mib", 0.0),
                    gen.get("lines", "?"),
                    gen.get("errors", {}).get("total", "?"),
                    fmt_number(base["wall_seconds"]["median"]) if base else "—",
                    fmt_number(cand["wall_seconds"]["median"]),
                    fmt_pct(change.get("wall_seconds_median_pct"))
                    if base
                    else "—",
                    fmt_number(base["peak_rss_mib"]["median"], 1) if base else "—",
                    fmt_number(cand["peak_rss_mib"]["median"], 1),
                    fmt_pct(change.get("peak_rss_mib_median_pct"))
                    if base
                    else "—",
                    fmt_number(cand["input_mib_per_second"]["median"], 1),
                    outputs,
                )
            )
    else:
        lines.append("No completed cases.")
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    checks = result.get("checks", {})
    for key in (
        "per_run_validity",
        "expected_analysis_matched",
        "within_version_sha_reproducible",
        "within_version_analysis_stable",
        "spike_schedule_stable_across_cases",
        "cross_version_consistent",
        "correctness_passed",
        "output_consistency_passed",
    ):
        value = checks.get(key)
        lines.append("- %s: %s" % (key, "PASS" if value else ("FAIL" if value is False else "N/A")))
    lines.append("")
    gates = result.get("gates", {})
    lines.append("## Gates")
    lines.append("")
    if not gates.get("enabled"):
        lines.append("Disabled. This run is report-only; no performance gate was applied.")
    elif gates.get("passed"):
        lines.append("Enabled and passed.")
    else:
        lines.append("Enabled and failed:")
        for failure in gates.get("failures", []):
            lines.append("- `%s`: %s" % (failure.get("case"), failure.get("detail")))
    lines.append("")
    if result.get("failure"):
        lines.append("## Failure")
        lines.append("")
        lines.append("```")
        lines.append(truncate(result["failure"].get("message", ""), 2000))
        lines.append("```")
        lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- Inputs are synthetic, deterministic, and generated in a temporary directory; they are not committed."
    )
    lines.append(
        "- The 24h UTC span and four incident buckets are fixed across scales, so spike intervals are directly comparable."
    )
    lines.append(
        "- Timing is warm-cache; generation and validation are excluded. P95 is reported only for at least 20 samples."
    )
    lines.append(
        "- `--allow-report-diff` / `--allow-report-format` are the only ways to relax cross-version output comparison; mandatory analysis fields are never relaxable."
    )
    lines.append(
        "- The script does not modify CI, core algorithms, or frontend code."
    )
    return "\n".join(lines) + "\n"


def write_outputs(result, output_path):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    markdown_path = output_path.with_suffix(".md")
    with markdown_path.open("x", encoding="utf-8") as stream:
        stream.write(markdown_summary(result))
    return output_path, markdown_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_sizes(value):
    sizes = []
    for token in value.split(","):
        token = token.strip()
        if not token:
            raise argparse.ArgumentTypeError("empty size in --sizes")
        try:
            size = int(token)
        except ValueError:
            raise argparse.ArgumentTypeError("invalid size: %r" % token)
        if size < 1:
            raise argparse.ArgumentTypeError("sizes must be positive")
        if size in sizes:
            raise argparse.ArgumentTypeError("duplicate size: %d" % size)
        sizes.append(size)
    return sorted(sizes)


def parse_allow_diff(values):
    keys = []
    for value in values:
        for token in value.split(","):
            token = token.strip()
            if not token:
                continue
            if token in MANDATORY_CORE_KEYS:
                raise argparse.ArgumentTypeError(
                    "cannot allow differences in mandatory analysis field: " + token
                )
            if token not in keys:
                keys.append(token)
    return keys


def build_parser():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--baseline", help="previous MoonLog binary (enables interleaving and comparison)")
    parser.add_argument("--candidate", default="bin/moonlog", help="candidate binary (default: bin/moonlog)")
    parser.add_argument(
        "--sizes",
        default=DEFAULT_SIZES,
        help="comma-separated nominal MiB sizes (default: %s); sizes above 1024 require --allow-large"
        % DEFAULT_SIZES,
    )
    parser.add_argument(
        "--allow-large",
        action="store_true",
        help="allow sizes above 1024 MiB (5 GiB and 10 GiB are never enabled by default)",
    )
    parser.add_argument("--timeout", type=float, default=600, help="maximum seconds per CLI process (default: 600)")
    parser.add_argument("--runs", type=int, default=5, help="measured runs per version per case (default: 5)")
    parser.add_argument("--warmups", type=int, default=1, help="warmups per version per case (default: 1)")
    parser.add_argument("--seed", type=int, default=BASE_SEED, help="base generation seed (default: %d)" % BASE_SEED)
    parser.add_argument(
        "--output",
        default="benchmarks/regression/results.json",
        help="JSON output path; a sibling .md summary is also written",
    )
    parser.add_argument("--work-dir", help="existing directory for temporary inputs (default: system temp)")
    parser.add_argument("--keep-work", action="store_true", help="retain generated inputs and captures")
    parser.add_argument(
        "--allow-report-diff",
        action="append",
        default=[],
        metavar="KEYS",
        help="comma-separated top-level report keys that may differ across versions; mandatory analysis fields are rejected",
    )
    parser.add_argument(
        "--allow-report-format",
        action="store_true",
        help="allow byte-level report differences when parsed report content is otherwise identical",
    )
    parser.add_argument("--gate", action="store_true", help="enable hard regression gates (default: report only)")
    parser.add_argument(
        "--gate-wall-pct",
        type=float,
        default=15.0,
        help="fail when candidate median wall time regresses by more than this percent (default: 15)",
    )
    parser.add_argument(
        "--gate-rss-pct",
        type=float,
        default=20.0,
        help="fail when candidate median peak RSS grows by more than this percent (default: 20)",
    )
    return parser


def resolve_binary(arg, parser):
    path = Path(arg).expanduser()
    if not path.is_file():
        parser.error("binary not found: %s" % arg)
    if not os.access(str(path), os.X_OK):
        parser.error("binary is not executable: %s" % arg)
    return path.resolve()


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        sizes = parse_sizes(args.sizes)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be finite and positive")
    if Path(args.output).exists() or Path(args.output).with_suffix(".md").exists():
        parser.error("output already exists; choose a new --output to preserve raw measurements")
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    if args.warmups < 0:
        parser.error("--warmups must not be negative")
    if not all(math.isfinite(x) and x > 0 for x in [args.gate_wall_pct, args.gate_rss_pct]):
        parser.error("gate thresholds must be positive")
    if any(size > LARGE_THRESHOLD_MIB for size in sizes) and not args.allow_large:
        parser.error(
            "sizes above %d MiB require --allow-large; 5 GiB and 10 GiB are never enabled by default"
            % LARGE_THRESHOLD_MIB
        )
    if args.gate and not args.baseline:
        parser.error("--gate requires --baseline")
    try:
        allow_diff = parse_allow_diff(args.allow_report_diff)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    candidate_path = resolve_binary(args.candidate, parser)
    baseline_path = resolve_binary(args.baseline, parser) if args.baseline else None

    root = Path(__file__).resolve().parents[2]
    started_at = utc_now()
    environment = environment_snapshot(root, started_at)
    candidate_info = {
        "path": args.candidate,
        "sha256": sha256_file(candidate_path),
        "bytes": candidate_path.stat().st_size,
    }
    baseline_info = None
    if baseline_path:
        baseline_info = {
            "path": args.baseline,
            "sha256": sha256_file(baseline_path),
            "bytes": baseline_path.stat().st_size,
        }
    same_binary = bool(
        baseline_info and baseline_info["sha256"] == candidate_info["sha256"]
    )
    binaries = {"candidate": candidate_info, "baseline": baseline_info, "same_binary": same_binary}

    work_parent = Path(args.work_dir).expanduser() if args.work_dir else Path(tempfile.gettempdir())
    if args.work_dir and not work_parent.is_dir():
        parser.error("--work-dir is not an existing directory: %s" % args.work_dir)
    work_root = Path(tempfile.mkdtemp(prefix="moonlog-regression-", dir=str(work_parent)))

    result = {
        "schema_version": 1,
        "tool": {
            "name": "moonlog-regression",
            "version": 1,
            "python_version": platform.python_version(),
        },
        "started_at_utc": started_at,
        "finished_at_utc": None,
        "environment": environment,
        "binaries": binaries,
        "parameters": {
            "seed": args.seed,
            "sizes_mib": sizes,
            "formats": list(FORMATS),
            "densities": list(DENSITIES),
            "warmups": args.warmups,
            "runs": args.runs,
            "interleaved": baseline_path is not None,
            "allow_large": bool(args.allow_large),
            "output": str(args.output),
            "work_dir": args.work_dir,
            "keep_work": bool(args.keep_work),
            "analysis": {
                "detector": "moving-average",
                "bucket_minutes": BUCKET_MINUTES,
                "baseline_buckets": BASELINE_BUCKETS,
                "multiplier": MULTIPLIER,
                "min_errors": MIN_ERRORS,
                "context_lines": CONTEXT_LINES,
                "context_mode": "spikes",
                "max_samples": MAX_SAMPLES,
                "sampling": "first",
                "scans_expected": SCANS,
                "report_format": "json",
            },
            "cli_options": CLI_OPTIONS,
            "generation": {
                "span_start_utc": SPAN_START.isoformat(),
                "span_end_utc": (SPAN_START + dt.timedelta(hours=24)).isoformat(),
                "bucket_minutes": BUCKET_MINUTES,
                "bucket_count": BUCKETS,
                "incident_buckets": list(INCIDENT_BUCKETS),
                "baseline_errors_per_1000_lines": DENSITIES,
                "incident_errors_per_1000_lines": INCIDENT_ERRORS_PER_1000,
                "fatal_every_nth_error": FATAL_EVERY,
                "untimed_lines": 0,
                "case_seed_policy": "seed + size_mib*1009 + format_index*131 + density_index*17",
            },
            "measurement": {
                "timer": "time.perf_counter around fork/exec/wait4",
                "wall_includes": "process startup, two input scans, parsing, aggregation, spike detection, context sampling, report write, terminal summary",
                "rss_method": "os.wait4 ru_maxrss (Darwin bytes, Linux KiB)",
                "allocations": "unsupported",
                "allocations_note": "no reliable cross-platform uniform allocation measurement; RSS is not used as allocations",
                "p95_method": "nearest-rank; reported only for at least 20 samples",
                "cache_state": "warm OS page cache; generation and validation excluded from timing",
                "input_throughput": "actual input bytes / elapsed wall seconds, two scans not counted twice",
                "lines_per_second": "logical input lines / elapsed wall seconds",
                "gates_default": "disabled",
            },
            "allow_report_diff": allow_diff,
            "allow_report_format": bool(args.allow_report_format),
            "gate": {
                "enabled": bool(args.gate),
                "wall_pct": args.gate_wall_pct,
                "rss_pct": args.gate_rss_pct,
            },
        },
        "cases": [],
        "checks": {
            "per_run_validity": True,
            "expected_analysis_matched": True,
            "within_version_sha_reproducible": True,
            "within_version_analysis_stable": True,
            "spike_schedule_stable_across_cases": True,
            "cross_version_consistent": None if not baseline_path else True,
            "correctness_passed": True,
            "output_consistency_passed": None if not baseline_path else True,
        },
        "gates": {
            "enabled": bool(args.gate),
            "thresholds": {
                "wall_median_pct": args.gate_wall_pct,
                "peak_rss_median_pct": args.gate_rss_pct,
                "output_consistency": True,
            },
            "evaluated": False,
            "passed": None,
            "failures": [],
        },
        "result": {
            "exit_code": 0,
            "correctness_passed": True,
            "output_consistency_passed": None if not baseline_path else True,
            "gates_passed": None,
        },
        "failure": None,
    }
    if same_binary:
        print(
            "note: baseline and candidate have the same SHA-256; this is a self-comparison",
            flush=True,
        )
    if args.keep_work:
        print(
            "warning: --keep-work retains every generated input; 5 GiB and 10 GiB runs can consume tens of GiB",
            flush=True,
        )
    if any(size > LARGE_THRESHOLD_MIB for size in sizes):
        print(
            "warning: large sizes are enabled explicitly; expect long runtimes and large temporary files",
            flush=True,
        )

    exit_code = 0
    try:
        binaries_for_run = {"candidate": str(candidate_path)}
        if baseline_path:
            binaries_for_run["baseline"] = str(baseline_path)
        for size in sizes:
            for fmt in FORMATS:
                for density in DENSITIES:
                    run_case(
                        (size, fmt, density),
                        binaries_for_run,
                        args,
                        work_root,
                        result,
                    )

        expected_schedules = [
            [(spike["start"], spike["end_exclusive"]) for spike in case["expected"]["spikes"]]
            for case in result["cases"]
        ]
        result["checks"]["spike_schedule_stable_across_cases"] = (
            len(expected_schedules) > 0
            and all(schedule == expected_schedules[0] for schedule in expected_schedules)
        )
        if not result["checks"]["spike_schedule_stable_across_cases"]:
            raise HarnessError("expected spike schedule differs across cases")

        for version, info in (("candidate", candidate_info), ("baseline", baseline_info)):
            if not info:
                continue
            current = sha256_file(
                candidate_path if version == "candidate" else baseline_path
            )
            info["stable_during_run"] = current == info["sha256"]
            if not info["stable_during_run"]:
                raise HarnessError("binary changed during the run: %s" % version)

        correctness = all(
            result["checks"][key]
            for key in (
                "per_run_validity",
                "expected_analysis_matched",
                "within_version_sha_reproducible",
                "within_version_analysis_stable",
                "spike_schedule_stable_across_cases",
            )
        )
        result["checks"]["correctness_passed"] = correctness
        result["checks"]["output_consistency_passed"] = (
            result["checks"]["cross_version_consistent"] if baseline_path else None
        )
        result["result"]["correctness_passed"] = correctness
        result["result"]["output_consistency_passed"] = result["checks"]["output_consistency_passed"]

        if not correctness:
            raise HarnessError("correctness checks failed")

        if args.gate:
            gates = result["gates"]
            gates["evaluated"] = True
            failures = []
            for case in result["cases"]:
                stats = case.get("statistics") or {}
                change = stats.get("change_pct") or {}
                wall_change = change.get("wall_seconds_median_pct")
                if wall_change is not None and wall_change > args.gate_wall_pct:
                    failures.append(
                        {
                            "case": case["name"],
                            "metric": "wall_seconds_median",
                            "change_pct": wall_change,
                            "threshold_pct": args.gate_wall_pct,
                            "detail": "wall median regressed by %.1f%% (limit %.1f%%)"
                            % (wall_change, args.gate_wall_pct),
                        }
                    )
                rss_change = change.get("peak_rss_mib_median_pct")
                if rss_change is not None and rss_change > args.gate_rss_pct:
                    failures.append(
                        {
                            "case": case["name"],
                            "metric": "peak_rss_mib_median",
                            "change_pct": rss_change,
                            "threshold_pct": args.gate_rss_pct,
                            "detail": "peak RSS median grew by %.1f%% (limit %.1f%%)"
                            % (rss_change, args.gate_rss_pct),
                        }
                    )
                cross = (case.get("verification") or {}).get("cross_version")
                if cross is not None and not cross.get("consistent"):
                    failures.append(
                        {
                            "case": case["name"],
                            "metric": "output_consistency",
                            "detail": "cross-version report content is inconsistent",
                        }
                    )
            gates["failures"] = failures
            gates["passed"] = not failures
            result["result"]["gates_passed"] = gates["passed"]
            if failures:
                exit_code = 1
        else:
            result["gates"]["passed"] = None
            if result["checks"]["cross_version_consistent"] is False:
                print(
                    "warning: cross-version output inconsistency was detected, but gates are disabled; exit code stays 0",
                    flush=True,
                )
    except KeyboardInterrupt:
        result["failure"] = {"stage": "interrupted", "message": "interrupted by user", "details": None}
        result["result"]["correctness_passed"] = False
        exit_code = 130
    except ValidityError as exc:
        result["failure"] = {
            "stage": "validation",
            "message": str(exc),
            "details": exc.details,
        }
        result["checks"]["per_run_validity"] = False
        result["checks"]["correctness_passed"] = False
        result["result"]["correctness_passed"] = False
        exit_code = 2
    except HarnessError as exc:
        result["failure"] = {"stage": "harness", "message": str(exc), "details": None}
        result["checks"]["correctness_passed"] = False
        result["result"]["correctness_passed"] = False
        exit_code = 2
    except Exception as exc:  # noqa: BLE001 - preserve partial results on unexpected failure
        import traceback

        result["failure"] = {
            "stage": "unexpected",
            "message": "%s: %s" % (type(exc).__name__, exc),
            "details": truncate(traceback.format_exc(), 4000),
        }
        result["checks"]["correctness_passed"] = False
        result["result"]["correctness_passed"] = False
        exit_code = 2
    finally:
        result["finished_at_utc"] = utc_now()
        result["result"]["exit_code"] = exit_code
        if args.keep_work:
            print("work directory retained: %s" % work_root, flush=True)
        else:
            shutil.rmtree(work_root, ignore_errors=True)
        output_path, markdown_path = write_outputs(result, args.output)
        print("results: %s" % output_path, flush=True)
        print("summary: %s" % markdown_path, flush=True)
        if result["failure"]:
            print("failure: %s" % result["failure"]["message"], flush=True)
        if exit_code == 0 and not args.gate:
            print("gates disabled: report-only run", flush=True)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
