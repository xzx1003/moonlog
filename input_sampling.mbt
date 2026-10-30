///|
// One analyzer receives every file in caller-specified order. Statistics are
// chronological; sampling order is file order then physical line order.
pub(all) enum SamplingMode {
  First
  Distributed
}

///|
pub fn SamplingMode::label(self : SamplingMode) -> String {
  match self {
    First => "first"
    Distributed => "distributed"
  }
}

///|
pub struct SamplingPlan {
  total : Int64
  ranks : Array[Int64]
}

///|
// Target ordinals are zero-based. Distributed chooses equally spaced target
// ordinals including endpoints; a single slot chooses the middle target.
// This distributes by matching occurrence, NOT elapsed time or per incident.
pub fn SamplingPlan::new(
  total : Int64,
  limit : Int32,
  mode : SamplingMode,
) -> SamplingPlan raise {
  guard total >= 0L && total <= 9000000000000L else {
    fail("target total must be 0..9000000000000")
  }
  guard limit >= 0 && limit <= 100 else { fail("sample limit must be 0..100") }
  let count = if total < limit.to_int64() { total.to_int() } else { limit }
  let ranks = Array::makei(count, fn(i) {
    match mode {
      First => i.to_int64()
      Distributed =>
        if count == 1 {
          total / 2L
        } else {
          i.to_int64() * (total - 1L) / (count - 1).to_int64()
        }
    }
  })
  { total, ranks, }
}

///|
pub fn SamplingPlan::ranks(self : SamplingPlan) -> Array[Int64] {
  self.ranks.copy()
}

///|
pub(all) struct FileContextWindow {
  source : String
  window : ContextWindow
}

///|
// Keeps one ring per active file; windows never cross file boundaries.
// File identity is the source string supplied by the host. The host must
// reject duplicate/aliased input files before scanning.
pub struct MultiFileContextCollector {
  config : Config
  plan : SamplingPlan
  completed : Array[FileContextWindow]
  mut current : ContextCollector?
  mut source : String
  mut seen_targets : Int64
  mut selected : Int32
}

///|
pub fn MultiFileContextCollector::new(
  config : Config,
  plan : SamplingPlan,
) -> MultiFileContextCollector raise {
  guard plan.ranks.length() <= config.max_samples else {
    fail("sampling plan exceeds configured sample limit")
  }
  {
    config,
    plan,
    completed: [],
    current: None,
    source: "",
    seen_targets: 0L,
    selected: 0,
  }
}

///|
fn MultiFileContextCollector::flush(self : MultiFileContextCollector) -> Unit {
  if self.current is Some(collector) {
    for window in collector.windows() {
      self.completed.push({ source: self.source, window, })
    }
  }
  self.current = None
}

///|
pub fn MultiFileContextCollector::begin_file(
  self : MultiFileContextCollector,
  source : String,
) -> Unit {
  self.flush()
  self.source = source
  self.current = Some(ContextCollector::new(self.config))
}

///|
pub fn MultiFileContextCollector::feed(
  self : MultiFileContextCollector,
  raw : String,
  target : Bool,
) -> Unit raise {
  guard self.current is Some(collector) else {
    fail("begin_file must precede feed")
  }
  let mut choose = false
  if target {
    if self.seen_targets >= self.plan.total {
      fail("target count changed between sampling passes")
    }
    if self.selected < self.plan.ranks.length() &&
      self.plan.ranks[self.selected] == self.seen_targets {
      choose = true
      self.selected += 1
    }
    self.seen_targets += 1L
  }
  collector.feed(raw, choose)
}

///|
// Must be called only after host verifies every input's line count and digest
// against earlier passes. Target count alone cannot detect changed contents.
pub fn MultiFileContextCollector::finish(
  self : MultiFileContextCollector,
) -> Array[FileContextWindow] raise {
  guard self.seen_targets == self.plan.total else {
    fail("target count changed between sampling passes")
  }
  self.flush()
  self.completed.copy()
}

///|
pub fn MultiFileContextCollector::sampled(
  self : MultiFileContextCollector,
) -> Int32 {
  self.selected
}

///|
pub fn MultiFileContextCollector::omitted(
  self : MultiFileContextCollector,
) -> Int64 {
  self.seen_targets - self.selected.to_int64()
}
