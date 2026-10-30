///|
// Median of a nonempty private scratch array; never mutates input buckets.
fn detector_median(values : Array[Double]) -> Double {
  values.sort_by(fn(a, b) { if a < b { -1 } else if a > b { 1 } else { 0 } })
  let mid = values.length() / 2
  if values.length() % 2 == 0 {
    (values[mid - 1] + values[mid]) / 2.0
  } else {
    values[mid]
  }
}

///|
// Error-count detectors. Prediction always precedes update (no look-ahead).
// EWMA seeds with the arithmetic mean of the first n buckets, then updates
// every bucket, including anomalies. MAD uses exactly the previous n buckets.
fn detect_adaptive_spikes(
  buckets : Array[Bucket],
  config : Config,
) -> Array[Spike] {
  let spikes : Array[Spike] = []
  let n = config.baseline_buckets
  if buckets.length() <= n {
    return spikes
  }
  let mut ewma = 0.0
  for i in 0..<n {
    ewma += buckets[i].errors.to_double() / n.to_double()
  }
  for i in n..<buckets.length() {
    let bucket = buckets[i]
    let current = bucket.errors.to_double()
    let (baseline, threshold) = match config.detector {
      Mad => {
        let values = Array::make(n, 0.0)
        for j in 0..<n {
          values[j] = buckets[i - n + j].errors.to_double()
        }
        let median = detector_median(values)
        let deviations = values.map(x => (x - median).abs())
        let scale = 1.4826 * detector_median(deviations)
        // Zero MAD falls back to strict current > median (still min_errors).
        (median, median + config.mad_threshold * scale)
      }
      _ => (ewma, ewma * config.multiplier.to_double())
    }
    if bucket.errors >= config.min_errors.to_int64() && current > threshold {
      let end = bucket.start + config.bucket_minutes.to_int64()
      match spikes.last() {
        Some(previous) if previous.end == bucket.start => {
          previous.end = end
          previous.errors += bucket.errors
          previous.peak_errors = previous.peak_errors.max(bucket.errors)
        }
        _ =>
          spikes.push({
            start: bucket.start,
            end,
            errors: bucket.errors,
            peak_errors: bucket.errors,
            baseline,
          })
      }
    }
    ewma = config.ewma_alpha * current + (1.0 - config.ewma_alpha) * ewma
  }
  spikes
}
