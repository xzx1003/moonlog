///|
// Host feeds <=64 KiB byte chunks, re-reading the same File for pass two.
// UTF-8 is decoded only at complete lines, so split codepoints are safe.
pub struct Session {
  analyzer : @engine.Analyzer
  config : @engine.Config
  source : String
  pending : @buffer.Buffer
  contexts : @engine.ContextCollector
  mut analysis : @engine.Analysis?
  mut signatures : @engine.SpikeSignatureCollector?
  mut phase : Int32
  mut lines : Int64
  mut first_lines : Int64
  mut digest : @engine.Sha256
  mut first_digest : String
  mut bytes : Int64
}

///|
pub fn Session::new(
  source : String,
  config : @engine.Config,
  filter~ : @engine.Filter = @engine.Filter::new(),
  json_fields~ : @engine.JsonFields = @engine.JsonFields::default(),
) -> Session {
  {
    analyzer: @engine.Analyzer::new(config, filter~, json_fields~),
    config,
    source,
    pending: @buffer.Buffer(),
    contexts: @engine.ContextCollector::new(config),
    analysis: None,
    signatures: None,
    phase: 1,
    lines: 0,
    first_lines: 0,
    digest: @engine.Sha256::new(),
    first_digest: "",
    bytes: 0L,
  }
}

///|
fn Session::emit(self : Session) -> Unit raise {
  let data = self.pending.to_bytes()
  let end = if data.length() > 0 && data[data.length() - 1] == 13 {
    data.length() - 1
  } else {
    data.length()
  }
  let raw = @utf8.decode(data[:end], ignore_bom=self.lines == 0) catch {
    _ => fail("invalid UTF-8")
  }
  self.pending.reset()
  self.lines += 1
  if self.phase == 1 {
    self.analyzer.feed(raw)
  } else {
    let analysis = self.analysis.unwrap()
    ignore(self.signatures.unwrap().feed(raw))
    self.contexts.feed(raw, analysis.is_target(raw))
  }
}

///|
pub fn Session::feed(self : Session, chunk : Bytes) -> Unit raise {
  guard self.phase == 1 || self.phase == 2 else {
    fail("session is not accepting input")
  }
  if chunk.length() > 65536 {
    self.phase = -1
    fail("chunk exceeds 64 KiB")
  }
  errdefer {
    self.phase = -1
  }
  self.bytes += chunk.length().to_int64()
  for byte in chunk {
    self.digest.feed_byte(byte)
    if byte == 10 {
      self.emit()
    } else {
      if self.pending.length() >= 65536 {
        fail("line exceeds 64 KiB")
      }
      self.pending.write_byte(byte)
    }
  }
}

///|
// Flush EOF; returns next phase: 2 means rewind File, 3 means report ready.
pub fn Session::end_pass(self : Session) -> Int32 raise {
  guard self.phase == 1 || self.phase == 2 else {
    fail("invalid session phase")
  }
  errdefer {
    self.phase = -1
  }

  if self.pending.length() > 0 {
    self.emit()
  }
  if self.phase == 1 {
    let analysis = self.analyzer.finish()
    self.analysis = Some(analysis)
    self.signatures = Some(@engine.SpikeSignatureCollector::new(analysis))
    self.first_lines = self.lines
    self.first_digest = self.digest.hex()
    self.lines = 0
    self.digest = @engine.Sha256::new()
    self.bytes = 0L
    self.phase = 2
  } else {
    guard self.lines == self.first_lines &&
      self.digest.hex() == self.first_digest else {
      fail("input changed between passes")
    }
    self.phase = 3
  }
  self.phase
}

///|
pub fn Session::cancel(self : Session) -> Unit {
  self.phase = -1
  self.pending.reset()
}

///|
pub fn Session::phase(self : Session) -> Int32 {
  self.phase
}

///|
// Bytes consumed in current pass; host supplies File.size for progress.
pub fn Session::bytes_processed(self : Session) -> Int64 {
  self.bytes
}

///|
pub fn Session::result(self : Session) -> @engine.ReportResult raise {
  guard self.phase == 3 else { fail("report is not ready") }
  let windows = self.contexts
    .windows()
    .map(window => @engine.FileContextWindow::{ source: self.source, window, })
  @engine.ReportResult::new(
    self.analysis.unwrap(),
    windows,
    self.contexts.sampled(),
    self.contexts.omitted(),
    self.signatures.unwrap(),
    Spikes,
    [self.source],
    sample_limit=self.config.max_samples,
  )
}
