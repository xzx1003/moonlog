///|
// The signature budget is shared across all (spike, signature) pairs.
// This keeps memory bounded independently of the number of spikes.
pub struct SpikeSignatureCollector {
  analysis : Analysis
  counts : Array[Map[String, Int64]]
  omitted : Array[Int64]
  mut retained : Int32
}

///|
pub fn SpikeSignatureCollector::new(
  analysis : Analysis,
) -> SpikeSignatureCollector {
  {
    analysis,
    counts: Array::makei(analysis.spikes.length(), _ => {}),
    omitted: Array::make(analysis.spikes.length(), 0),
    retained: 0,
  }
}

///|
// Returns the same target predicate used by context extraction.
pub fn SpikeSignatureCollector::feed(
  self : SpikeSignatureCollector,
  raw : String,
) -> Bool {
  let record = parse_line(raw, fields=self.analysis.json_fields)
  if !record.level.is_error() || !self.analysis.filter.accepts(record) {
    return false
  }
  guard record.minute is Some(minute) else { return false }
  let mut lo = 0
  let mut hi = self.analysis.spikes.length()
  while lo < hi {
    let middle = (lo + hi) / 2
    let spike = self.analysis.spikes[middle]
    if minute < spike.start {
      hi = middle
    } else if minute >= spike.end {
      lo = middle + 1
    } else {
      let signature = error_signature(record)
      let counts = self.counts[middle]
      if counts.contains(signature) {
        counts[signature] = counts.get_or_default(signature, 0) + 1
      } else if self.retained < self.analysis.config.max_signatures {
        counts[signature] = 1
        self.retained += 1
      } else {
        self.omitted[middle] += 1
      }
      return true
    }
  }
  false
}

///|
// Index corresponds to Analysis.spikes; ties use ascending signature text.
pub fn SpikeSignatureCollector::signatures(
  self : SpikeSignatureCollector,
  index : Int32,
) -> Array[Signature] {
  let result = self.counts[index]
    .to_array()
    .map(pair => { text: pair.0, count: pair.1, })
  result.sort_by(fn(a, b) {
    if a.count == b.count {
      a.text.compare(b.text)
    } else {
      b.count.compare(a.count)
    }
  })
  result
}

///|
// Counts error occurrences, not distinct signatures, excluded by the budget.
pub fn SpikeSignatureCollector::omitted(
  self : SpikeSignatureCollector,
  index : Int32,
) -> Int64 {
  self.omitted[index]
}
