///|
pub(all) struct SourceLine {
  number : Int32
  text : String
} derive(Eq, Debug)

///|
#deprecated
pub extend SourceLine with Eq::{equal, not_equal}

///|
#deprecated
pub extend SourceLine with @debug.Debug::{to_repr}

///|
pub struct RingBuffer {
  capacity : Int32
  slots : Array[SourceLine]
  mut next : Int32
}

///|
pub fn RingBuffer::new(capacity : Int32) -> RingBuffer {
  { capacity: if capacity < 0 { 0 } else { capacity }, slots: [], next: 0, }
}

///|
pub fn RingBuffer::push(self : RingBuffer, line : SourceLine) -> Unit {
  if self.capacity == 0 {
    return
  }
  if self.slots.length() < self.capacity {
    self.slots.push(line)
  } else {
    self.slots[self.next] = line
  }
  self.next = (self.next + 1) % self.capacity
}

///|
pub fn RingBuffer::snapshot(self : RingBuffer) -> Array[SourceLine] {
  if self.slots.length() < self.capacity {
    return self.slots.copy()
  }
  [
    for i in 0..<self.slots.length() => {
      self.slots[(self.next + i) % self.capacity]
    }
  ]
}

///|
pub(all) struct ContextWindow {
  lines : Array[SourceLine]
  targets : Array[Int32]
  mut end_line : Int32
}

///|
pub struct ContextCollector {
  before : RingBuffer
  radius : Int32
  max_samples : Int32
  windows : Array[ContextWindow]
  mut seen : Int32
  mut sampled : Int32
  mut omitted : Int32
}

///|
pub fn ContextCollector::new(config : Config) -> ContextCollector {
  {
    before: RingBuffer::new(config.context),
    radius: config.context,
    max_samples: config.max_samples,
    windows: [],
    seen: 0,
    sampled: 0,
    omitted: 0,
  }
}

///|
pub fn ContextCollector::feed(
  self : ContextCollector,
  text : String,
  target : Bool,
) -> Unit {
  self.seen += 1
  let line = { number: self.seen, text, }
  let previous = self.windows.last()
  if previous is Some(window) && self.seen <= window.end_line {
    window.lines.push(line)
  }
  if target {
    if self.sampled >= self.max_samples {
      self.omitted += 1
    } else {
      self.sampled += 1
      let start = self.seen - self.radius
      match previous {
        Some(window) if start <= window.end_line + 1 => {
          let last = window.lines.last().unwrap().number
          for old in self.before.snapshot() {
            if old.number > last {
              window.lines.push(old)
            }
          }
          if window.lines.last().unwrap().number != self.seen {
            window.lines.push(line)
          }
          window.targets.push(self.seen)
          window.end_line = self.seen + self.radius
        }
        _ => {
          let lines = self.before.snapshot()
          lines.push(line)
          self.windows.push({
            lines,
            targets: [self.seen],
            end_line: self.seen + self.radius,
          })
        }
      }
    }
  }
  self.before.push(line)
}

///|
pub fn ContextCollector::windows(
  self : ContextCollector,
) -> Array[ContextWindow] {
  self.windows
}

///|
pub fn ContextCollector::sampled(self : ContextCollector) -> Int32 {
  self.sampled
}

///|
pub fn ContextCollector::omitted(self : ContextCollector) -> Int32 {
  self.omitted
}
