///|
// Exact normalized signature comparison. Counts use the same filters as spike
// detection. Baseline is the configured complete window before spike start;
// it can contain earlier incidents and is not assumed to be healthy.
pub(all) struct SignatureComparison {
  signature : String
  before_start : Int64
  spike_start : Int64
  spike_end : Int64
  before_minutes : Int64
  spike_minutes : Int64
  before_count : Int64
  spike_count : Int64
  before_per_minute : Double
  spike_per_minute : Double
  rate_multiplier : Double?
}

///|
pub struct SignatureComparisonCollector {
  analysis : Analysis
  signature : String
  before : Array[Int64]
  during : Array[Int64]
}

///|
pub fn SignatureComparisonCollector::new(
  analysis : Analysis,
  signature : String,
) -> SignatureComparisonCollector {
  {
    analysis,
    signature,
    before: Array::make(analysis.spikes.length(), 0L),
    during: Array::make(analysis.spikes.length(), 0L),
  }
}

///|
// Feed EVERY input line in the existing second pass, independent of context
// sampling and signature capacity. Only counters per spike are retained.
pub fn SignatureComparisonCollector::feed(
  self : SignatureComparisonCollector,
  raw : String,
) -> Unit {
  let record = parse_line(raw)
  if !record.level.is_error() ||
    !self.analysis.filter.accepts(record) ||
    error_signature(record) != self.signature {
    return
  }
  guard record.minute is Some(t) else { return }
  let spikes = self.analysis.spikes
  let width = self.analysis.config.bucket_minutes.to_int64() *
    self.analysis.config.baseline_buckets.to_int64()
  // Skip intervals already ended. Baseline windows may overlap: an occurrence
  // can legitimately contribute to several different comparisons.
  let mut lo = 0
  let mut hi = spikes.length()
  while lo < hi {
    let mid = (lo + hi) / 2
    if spikes[mid].end <= t {
      lo = mid + 1
    } else {
      hi = mid
    }
  }
  for i = lo; i < spikes.length(); i = i + 1 {
    let spike = spikes[i]
    if spike.start - width > t {
      break
    }
    if t < spike.start {
      self.before[i] += 1L
    } else {
      self.during[i] += 1L
    }
  }
}

///|
pub fn SignatureComparisonCollector::comparisons(
  self : SignatureComparisonCollector,
) -> Array[SignatureComparison] {
  let width = self.analysis.config.bucket_minutes.to_int64() *
    self.analysis.config.baseline_buckets.to_int64()
  Array::makei(self.analysis.spikes.length(), fn(i) {
    let spike = self.analysis.spikes[i]
    let duration = spike.end - spike.start
    let before_rate = self.before[i].to_double() / width.to_double()
    let spike_rate = self.during[i].to_double() / duration.to_double()
    {
      signature: self.signature,
      before_start: spike.start - width,
      spike_start: spike.start,
      spike_end: spike.end,
      before_minutes: width,
      spike_minutes: duration,
      before_count: self.before[i],
      spike_count: self.during[i],
      before_per_minute: before_rate,
      spike_per_minute: spike_rate,
      rate_multiplier: if self.before[i] == 0L {
        None
      } else {
        Some(spike_rate / before_rate)
      },
    }
  })
}

///|
pub fn SignatureComparison::to_json(self : SignatureComparison) -> Json {
  Json::object({
    "signature": Json(self.signature),
    "before_start": Json(format_time(self.before_start)),
    "spike_start": Json(format_time(self.spike_start)),
    "spike_end_exclusive": Json(format_time(self.spike_end)),
    "before_minutes": Json(self.before_minutes),
    "spike_minutes": Json(self.spike_minutes),
    "before_count": Json(self.before_count),
    "spike_count": Json(self.spike_count),
    "before_per_minute": Json(self.before_per_minute),
    "spike_per_minute": Json(self.spike_per_minute),
    "rate_multiplier": match self.rate_multiplier {
      Some(x) => Json(x)
      None => Json::null()
    },
  })
}
