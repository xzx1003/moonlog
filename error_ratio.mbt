///|
// Counts time-valid physical records inside time filters, before level/keyword
// filtering. Unknown-level timed records are in the denominator. Untimed lines
// are excluded. This is a log-line ratio, never a request failure rate.
pub(all) struct LogErrorRatio {
  total : Int64
  errors : Int64
  fraction : Double?
}

///|
fn log_error_ratio(total : Int64, errors : Int64) -> LogErrorRatio {
  {
    total,
    errors,
    fraction: if total == 0L {
      None
    } else {
      Some(errors.to_double() / total.to_double())
    },
  }
}

///|
pub fn Bucket::log_error_ratio(self : Bucket) -> LogErrorRatio {
  log_error_ratio(self.total.to_int64(), self.errors.to_int64())
}

///|
// Optional interval is [start, end); boundaries must be UTC bucket boundaries.
// No interval gives the whole observation range. Empty ranges yield None ratio.
pub fn Analysis::log_error_ratio(
  self : Analysis,
  start~ : Int64? = None,
  end~ : Int64? = None,
) -> LogErrorRatio {
  let buckets = self.observation_buckets
  let mut lo = 0
  let mut hi = buckets.length()
  if start is Some(start) {
    while lo < hi {
      let mid = (lo + hi) / 2
      if buckets[mid].start < start {
        lo = mid + 1
      } else {
        hi = mid
      }
    }
  }
  let mut total = 0L
  let mut errors = 0L
  for i = lo; i < buckets.length(); i = i + 1 {
    let b = buckets[i]
    if end is Some(end) && b.start >= end {
      break
    }
    total += b.total.to_int64()
    errors += b.errors.to_int64()
  }
  log_error_ratio(total, errors)
}

///|
pub fn LogErrorRatio::to_json(self : LogErrorRatio) -> Json {
  Json::object({
    "total": Json(self.total),
    "errors": Json(self.errors),
    "fraction": match self.fraction {
      Some(value) => Json(value)
      None => Json::null()
    },
  })
}
