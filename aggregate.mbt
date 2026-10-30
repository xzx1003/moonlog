///|
pub struct Analyzer {
  json_fields : JsonFields
  config : Config
  filter : Filter
  observation : Map[Int64, Bucket]
  buckets : Map[Int64, Bucket]
  signatures : Map[String, Int64]
  counts : Map[String, Int64]
  mut total : Int64
  mut matched : Int64
  mut untimed : Int64
  mut overflow_signatures : Int64
  mut first : Int64?
  mut last : Int64?
}

///|
pub fn Analyzer::new(
  config : Config,
  filter~ : Filter = Filter::new(),
  json_fields~ : JsonFields = JsonFields::default(),
) -> Analyzer {
  {
    config,
    json_fields,
    filter,
    observation: {},
    buckets: {},
    signatures: {},
    counts: {},
    total: 0,
    matched: 0,
    untimed: 0,
    overflow_signatures: 0,
    first: None,
    last: None,
  }
}

///|
pub fn Analyzer::feed(self : Analyzer, raw : String) -> Unit raise {
  guard self.total < 9000000000000L else {
    fail("input exceeds supported record limit (9000000000000)")
  }
  self.total += 1
  let record = parse_line(raw, fields=self.json_fields)
  // The observation interval comes from time-valid input, not just matching
  // errors. Otherwise --level ERROR would erase the preceding healthy baseline.
  if record.minute is Some(minute) &&
    (self.filter.from is None || minute >= self.filter.from.unwrap()) &&
    (self.filter.to is None || minute <= self.filter.to.unwrap()) {
    let width = self.config.bucket_minutes.to_int64()
    let start = minute / width * width
    let first = match self.first {
      Some(x) => if x < start { x } else { start }
      None => start
    }
    let last = match self.last {
      Some(x) => if x > start { x } else { start }
      None => start
    }
    if (last - first) / width >= self.config.max_buckets.to_int64() {
      fail(
        "time range exceeds max buckets; narrow --from/--to or increase --bucket-minutes",
      )
    }
    self.first = Some(first)
    self.last = Some(last)
    let observed = self.observation.get_or_init(start, fn() {
      { start, total: 0, errors: 0, }
    })
    observed.total += 1
    if record.level.is_error() {
      observed.errors += 1
    }
  }
  if !self.filter.accepts(record) {
    return
  }
  self.matched += 1
  let label = record.level.label()
  self.counts[label] = self.counts.get_or_default(label, 0) + 1
  if record.level.is_error() {
    let signature = error_signature(record)
    if self.signatures.contains(signature) ||
      self.signatures.length() < self.config.max_signatures {
      self.signatures[signature] = self.signatures.get_or_default(signature, 0) +
        1
    } else {
      self.overflow_signatures += 1
    }
  }
  guard record.minute is Some(minute) else {
    self.untimed += 1
    return
  }
  let width = self.config.bucket_minutes.to_int64()
  let start = minute / width * width
  let bucket = self.buckets.get_or_init(start, fn() {
    { start, total: 0, errors: 0, }
  })
  bucket.total += 1
  if record.level.is_error() {
    bucket.errors += 1
  }
}

///|
pub(all) struct Analysis {
  json_fields : JsonFields
  config : Config
  filter : Filter
  total : Int64
  matched : Int64
  untimed : Int64
  counts : Map[String, Int64]
  observation_buckets : Array[Bucket]
  buckets : Array[Bucket]
  spikes : Array[Spike]
  signatures : Array[Signature]
  overflow_signatures : Int64
}

///|
pub fn Analyzer::finish(self : Analyzer) -> Analysis {
  let buckets : Array[Bucket] = []
  let observation_buckets : Array[Bucket] = []
  if self.first is Some(first) && self.last is Some(last) {
    let width = self.config.bucket_minutes.to_int64()
    for start = first; start <= last; start = start + width {
      observation_buckets.push(
        self.observation.get_or_default(start, { start, total: 0, errors: 0, }),
      )
      buckets.push(
        self.buckets.get_or_default(start, { start, total: 0, errors: 0, }),
      )
    }
  }
  let signatures = self.signatures
    .to_array()
    .map(fn(pair) { { text: pair.0, count: pair.1, } })
  signatures.sort_by(fn(a, b) {
    if a.count == b.count {
      a.text.compare(b.text)
    } else {
      b.count.compare(a.count)
    }
  })
  {
    json_fields: self.json_fields,
    config: self.config,
    filter: self.filter,
    total: self.total,
    matched: self.matched,
    untimed: self.untimed,
    counts: self.counts.copy(),
    buckets,
    observation_buckets,
    spikes: detect_spikes(buckets, self.config),
    signatures,
    overflow_signatures: self.overflow_signatures,
  }
}

///|
pub fn detect_spikes(buckets : Array[Bucket], config : Config) -> Array[Spike] {
  let spikes : Array[Spike] = []
  let n = config.baseline_buckets
  let mut sum = 0L
  for i in 0..<buckets.length() {
    let bucket = buckets[i]
    if i >= n {
      let high = bucket.errors >= config.min_errors.to_int64() &&
        (
          sum == 0L ||
          bucket.errors * n.to_int64() > config.multiplier.to_int64() * sum
        )
      if high {
        let end = bucket.start + config.bucket_minutes.to_int64()
        match spikes.last() {
          Some(previous) if previous.end == bucket.start => {
            previous.end = end
            previous.errors += bucket.errors
            if bucket.errors > previous.peak_errors {
              previous.peak_errors = bucket.errors
            }
          }
          _ =>
            spikes.push({
              start: bucket.start,
              end,
              errors: bucket.errors,
              peak_errors: bucket.errors,
              baseline: sum.to_double() / n.to_double(),
            })
        }
      }
      sum -= buckets[i - n].errors
    }
    sum += bucket.errors
  }
  spikes
}

///|
pub fn Analysis::is_target(
  self : Analysis,
  raw : String,
  mode~ : ContextMode = Spikes,
  signature~ : String? = None,
) -> Bool {
  let record = parse_line(raw, fields=self.json_fields)
  if !record.level.is_error() || !self.filter.accepts(record) {
    return false
  }
  if signature is Some(text) && error_signature(record) != text {
    return false
  }
  // In Errors mode, untimed errors are eligible only when the filter accepts
  // them (a from/to bound excludes untimed records). Context remains physical
  // source lines, so neighboring lines need not satisfy the target filter.
  if mode == Errors {
    return true
  }
  guard record.minute is Some(minute) else { return false }
  let mut lo = 0
  let mut hi = self.spikes.length()
  while lo < hi {
    let middle = (lo + hi) / 2
    let spike = self.spikes[middle]
    if minute < spike.start {
      hi = middle
    } else if minute >= spike.end {
      lo = middle + 1
    } else {
      return true
    }
  }
  false
}
