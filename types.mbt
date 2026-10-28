///|
pub(all) enum Level {
  Debug
  Info
  Warn
  Error
  Fatal
  Other
} derive(Eq, Debug)

///|
pub fn Level::label(self : Level) -> String {
  match self {
    Debug => "DEBUG"
    Info => "INFO"
    Warn => "WARN"
    Error => "ERROR"
    Fatal => "FATAL"
    Other => "OTHER"
  }
}

///|
pub fn Level::is_error(self : Level) -> Bool {
  self == Error || self == Fatal
}

///|
pub(all) struct Record {
  minute : Int64?
  level : Level
  message : String
} derive(Eq, Debug)

///|
pub(all) struct Filter {
  level : Level?
  keyword : String
  from : Int64?
  to : Int64?
} derive(Debug)

///|
pub fn Filter::new() -> Filter {
  { level: None, keyword: "", from: None, to: None, }
}

///|
pub fn Filter::accepts(self : Filter, record : Record) -> Bool {
  if self.level is Some(level) && record.level != level {
    return false
  }
  if self.keyword != "" && !record.message.contains(self.keyword) {
    return false
  }
  if self.from is Some(start) {
    guard record.minute is Some(t) && t >= start else { return false }
  }
  if self.to is Some(end) {
    guard record.minute is Some(t) && t <= end else { return false }
  }
  true
}

///|
pub(all) struct Config {
  bucket_minutes : Int32
  baseline_buckets : Int32
  multiplier : Int32
  min_errors : Int32
  context : Int32
  max_samples : Int32
  max_buckets : Int32
  max_signatures : Int32
} derive(Debug)

///|
pub fn Config::new(
  bucket_minutes~ : Int32 = 5,
  baseline_buckets~ : Int32 = 6,
  multiplier~ : Int32 = 3,
  min_errors~ : Int32 = 3,
  context~ : Int32 = 10,
  max_samples~ : Int32 = 20,
  max_buckets~ : Int32 = 100000,
  max_signatures~ : Int32 = 1000,
) -> Config raise {
  guard bucket_minutes > 0 && bucket_minutes <= 1440 else {
    fail("bucket minutes must be 1..1440")
  }
  guard baseline_buckets > 0 && baseline_buckets <= 1000 else {
    fail("baseline buckets must be 1..1000")
  }
  guard multiplier >= 2 && multiplier <= 1000 else {
    fail("multiplier must be 2..1000")
  }
  guard min_errors > 0 else { fail("minimum errors must be positive") }
  guard context >= 0 && context <= 100 else { fail("context must be 0..100") }
  guard max_samples >= 0 && max_samples <= 100 else {
    fail("max samples must be 0..100")
  }
  guard max_buckets > 0 && max_buckets <= 1000000 else {
    fail("max buckets must be 1..1000000")
  }
  guard max_signatures > 0 && max_signatures <= 10000 else {
    fail("max signatures must be 1..10000")
  }
  {
    bucket_minutes,
    baseline_buckets,
    multiplier,
    min_errors,
    context,
    max_samples,
    max_buckets,
    max_signatures,
  }
}

///|
pub(all) struct Bucket {
  start : Int64
  mut total : Int32
  mut errors : Int32
} derive(Debug)

///|
pub(all) struct Spike {
  start : Int64
  mut end : Int64
  mut errors : Int32
  mut peak_errors : Int32
  baseline : Double
} derive(Debug)

///|
pub(all) struct Signature {
  text : String
  count : Int32
} derive(Debug)

///|
#deprecated
pub extend Level with @debug.Debug::{to_repr}

///|
#deprecated
pub extend Record with @debug.Debug::{to_repr}

///|
#deprecated
pub extend Filter with @debug.Debug::{to_repr}

///|
#deprecated
pub extend Config with @debug.Debug::{to_repr}

///|
#deprecated
pub extend Bucket with @debug.Debug::{to_repr}

///|
#deprecated
pub extend Spike with @debug.Debug::{to_repr}

///|
#deprecated
pub extend Signature with @debug.Debug::{to_repr}

///|
#deprecated
pub extend Level with Eq::{equal, not_equal}

///|
#deprecated
pub extend Record with Eq::{equal, not_equal}
