///|
fn detector_buckets(values : Array[Int64]) -> Array[@cli.Bucket] {
  let result : Array[@cli.Bucket] = []
  for i, errors in values {
    result.push({ start: i.to_int64() * 5L, total: errors + 100L, errors, })
  }
  result
}

///|
test "EWMA uses prior prediction and merges adjacent detections" {
  let b = detector_buckets([2L, 2L, 2L, 7L, 15L, 1L])
  let c = @cli.Config::new(detector=Ewma, baseline_buckets=3, ewma_alpha=0.5)
  let s = @cli.detect_spikes(b, c)
  assert_eq(s.length(), 1)
  assert_eq(s[0].start, 15L)
  assert_eq(s[0].end, 25L)
  assert_eq(s[0].errors, 22L)
  assert_eq(s[0].baseline, 2.0)
  assert_eq(s[0].peak_errors, 15L)
}

///|
test "EWMA strict threshold warmup and zero reference" {
  let c = @cli.Config::new(detector=Ewma, baseline_buckets=2, ewma_alpha=1.0)
  assert_eq(@cli.detect_spikes(detector_buckets([0L, 0L]), c).length(), 0)
  let s = @cli.detect_spikes(detector_buckets([0L, 0L, 3L, 9L, 28L]), c)
  assert_eq(s.length(), 2) // 9 == 3*3 is not a spike; alpha=1 predicts last bucket.
  assert_eq(s[0].start, 10L)
  assert_eq(s[1].start, 20L)
}

///|
test "MAD even median normalized scale and strict boundary" {
  let c = @cli.Config::new(detector=Mad, baseline_buckets=4, mad_threshold=1.0)
  // median 3; MAD 1; upper limit 4.4826.
  assert_eq(
    @cli.detect_spikes(detector_buckets([1L, 3L, 3L, 5L, 4L]), c).length(),
    0,
  )
  let s = @cli.detect_spikes(detector_buckets([1L, 3L, 3L, 5L, 5L]), c)
  assert_eq(s.length(), 1)
  assert_eq(s[0].baseline, 3.0)
}

///|
test "MAD excludes current bucket and tolerates isolated prior outlier" {
  let c = @cli.Config::new(detector=Mad, baseline_buckets=5)
  let s = @cli.detect_spikes(detector_buckets([1L, 1L, 100L, 1L, 1L, 3L]), c)
  assert_eq(s.length(), 1)
  assert_eq(s[0].baseline, 1.0)
  assert_eq(
    @cli.detect_spikes(detector_buckets([0L, 0L, 0L, 0L, 0L, 2L]), c).length(),
    0,
  )
}

///|
test "adaptive detectors keep Int64 counts and leave buckets unchanged" {
  for detector in [@cli.Detector::MovingAverage, Ewma, Mad] {
    let b = detector_buckets([2147483648L, 2147483648L, 8589934592L])
    let c = @cli.Config::new(detector~, baseline_buckets=2)
    let s = @cli.detect_spikes(b, c)
    assert_eq(s.length(), 1)
    assert_eq(s[0].errors, 8589934592L)
    assert_eq(b[0].errors, 2147483648L)
  }
}

///|
test "detector settings reject invalid floating parameters" {
  for alpha in [0.0, -0.1, 1.1, 0.0 / 0.0, 1.0 / 0.0] {
    let mut rejected = false
    ignore(@cli.Config::new(ewma_alpha=alpha)) catch {
      _ => rejected = true
    }
    assert_true(rejected)
  }
  for threshold in [0.0, -1.0, 1001.0, 0.0 / 0.0, 1.0 / 0.0] {
    let mut rejected = false
    ignore(@cli.Config::new(mad_threshold=threshold)) catch {
      _ => rejected = true
    }
    assert_true(rejected)
  }
}

///|
test "Analyzer dispatches selected detector without changing counts" {
  let a = @cli.Analyzer::new(@cli.Config::new(detector=Mad, baseline_buckets=1))
  a.feed("2026-10-28 08:00:00 [INFO] ok")
  for _ in 0..<3 {
    a.feed("2026-10-28 08:05:00 [ERROR] timeout")
  }
  let result = a.finish()
  assert_eq(result.total, 4L)
  assert_eq(result.spikes.length(), 1)
}

///|
test "MAD strict zero-scale equality and no warmup candidates" {
  let c = @cli.Config::new(detector=Mad, baseline_buckets=2)
  assert_eq(@cli.detect_spikes([], c).length(), 0)
  assert_eq(@cli.detect_spikes(detector_buckets([3L, 3L, 3L]), c).length(), 0)
}

///|
test "EWMA sustained incident is eventually absorbed by design" {
  let c = @cli.Config::new(detector=Ewma, baseline_buckets=2, ewma_alpha=1.0)
  let s = @cli.detect_spikes(detector_buckets([1L, 1L, 20L, 20L, 20L]), c)
  assert_eq(s.length(), 1)
  assert_eq(s[0].start, 10L)
  assert_eq(s[0].end, 15L)
}
