///|
test "distributed sampling exact endpoints middle and bounded count" {
  assert_eq(@cli.SamplingPlan::new(10L, 4, Distributed).ranks(), [
    0L, 3L, 6L, 9L,
  ])
  assert_eq(@cli.SamplingPlan::new(10L, 1, Distributed).ranks(), [5L])
  assert_eq(@cli.SamplingPlan::new(10L, 4, First).ranks(), [0L, 1L, 2L, 3L])
  assert_eq(@cli.SamplingPlan::new(2L, 20, Distributed).ranks(), [0L, 1L])
  assert_eq(@cli.SamplingPlan::new(0L, 20, Distributed).ranks(), [])
  assert_eq(@cli.SamplingPlan::new(10L, 0, Distributed).ranks(), [])
  let ranks = @cli.SamplingPlan::new(2147483647L, 100, Distributed).ranks()
  assert_eq(ranks.length(), 100)
  assert_eq(ranks[99], 2147483646L)
  for i in 1..<ranks.length() {
    assert_true(ranks[i] > ranks[i - 1])
  }
  assert_eq(@cli.SamplingMode::Distributed.label(), "distributed")
}

///|
test "multifile contexts preserve source local line numbers and global sample budget" {
  let config = @cli.Config::new(context=1, max_samples=2)
  let collector = @cli.MultiFileContextCollector::new(
    config,
    @cli.SamplingPlan::new(4L, 2, Distributed),
  )
  collector.begin_file("old.log")
  collector.feed("before old", false)
  collector.feed("old target", true)
  collector.feed("old omitted", true)
  collector.begin_file("empty.log")
  collector.begin_file("new.log")
  collector.feed("new omitted", true)
  collector.feed("new target", true)
  collector.feed("after new", false)
  let windows = collector.finish()
  assert_eq(windows.length(), 2)
  assert_eq(windows[0].source, "old.log")
  assert_eq(windows[0].window.targets, [2])
  assert_eq(windows[0].window.lines.map(line => line.number), [1, 2, 3])
  assert_eq(windows[1].source, "new.log")
  assert_eq(windows[1].window.targets, [2])
  assert_eq(windows[1].window.lines.map(line => line.number), [1, 2, 3])
  assert_eq(windows[1].window.lines[0].text, "new omitted")
  assert_eq(collector.sampled(), 2)
  assert_eq(collector.omitted(), 2L)
  assert_eq(collector.finish().length(), 2)
}

///|
test "multiple file lines share chronological statistics without requiring sorted files" {
  let analyzer = @cli.Analyzer::new(@cli.Config::new(baseline_buckets=1))
  // New file first, then older rotation; source order must not change counts.
  for
    line in [
      "2026-10-28 08:05:00 [ERROR] a", "2026-10-28 08:05:00 [ERROR] b", "2026-10-28 08:05:00 [ERROR] c",
      "2026-10-28 08:00:00 [INFO] healthy",
    ] {
    analyzer.feed(line)
  }
  let analysis = analyzer.finish()
  assert_eq(analysis.total, 4)
  assert_eq(analysis.spikes.length(), 1)
  assert_eq(analysis.spikes[0].errors, 3)
  assert_eq(analysis.log_error_ratio().fraction, Some(0.75))
}

///|
test "sampling detects target count changes and missing file setup" {
  let config = @cli.Config::new()
  let collector = @cli.MultiFileContextCollector::new(
    config,
    @cli.SamplingPlan::new(1L, 1, Distributed),
  )
  let missing = try {
    collector.feed("line", true)
    false
  } catch {
    _ => true
  }
  assert_true(missing)
  collector.begin_file("a.log")
  let fewer = try {
    ignore(collector.finish())
    false
  } catch {
    _ => true
  }
  assert_true(fewer)
  collector.feed("line", true)
  let extra = try {
    collector.feed("extra", true)
    false
  } catch {
    _ => true
  }
  assert_true(extra)
}

///|
test "first sampling selects the leading targets across files with a shared budget" {
  let config = @cli.Config::new(context=0, max_samples=3)
  let collector = @cli.MultiFileContextCollector::new(
    config,
    @cli.SamplingPlan::new(5L, 3, First),
  )
  collector.begin_file("a.log")
  collector.feed("a1", true)
  collector.feed("a2", true)
  collector.begin_file("b.log")
  collector.feed("b1", true)
  collector.feed("b2", true)
  collector.feed("b3", true)
  let windows = collector.finish()
  assert_eq(collector.sampled(), 3)
  assert_eq(collector.omitted(), 2L)
  assert_eq(windows.length(), 2)
  assert_eq(windows[0].source, "a.log")
  assert_eq(windows[0].window.targets, [1, 2])
  assert_eq(windows[1].source, "b.log")
  assert_eq(windows[1].window.targets, [1])
}

///|
test "zero limit and zero targets produce no windows without error" {
  let config = @cli.Config::new(context=0)
  let empty = @cli.MultiFileContextCollector::new(
    config,
    @cli.SamplingPlan::new(0L, 5, Distributed),
  )
  empty.begin_file("a.log")
  empty.feed("line", false)
  assert_eq(empty.finish().length(), 0)
  assert_eq(empty.sampled(), 0)
  assert_eq(empty.omitted(), 0L)

  let zero = @cli.MultiFileContextCollector::new(
    @cli.Config::new(context=0, max_samples=0),
    @cli.SamplingPlan::new(3L, 0, Distributed),
  )
  zero.begin_file("a.log")
  zero.feed("t1", true)
  zero.feed("t2", true)
  zero.feed("t3", true)
  assert_eq(zero.finish().length(), 0)
  assert_eq(zero.sampled(), 0)
  assert_eq(zero.omitted(), 3L)
}

///|
test "unselected targets still appear as neighboring context lines" {
  let config = @cli.Config::new(context=1)
  // One slot, distributed, middle of three targets across two files.
  let collector = @cli.MultiFileContextCollector::new(
    config,
    @cli.SamplingPlan::new(3L, 1, Distributed),
  )
  collector.begin_file("a.log")
  collector.feed("a target", true) // target 0 (unselected)
  collector.begin_file("b.log")
  collector.feed("b target", true) // target 1 (selected, middle)
  collector.feed("c target", true) // target 2 (unselected)
  let windows = collector.finish()
  assert_eq(collector.sampled(), 1)
  assert_eq(collector.omitted(), 2L)
  assert_eq(windows.length(), 1)
  assert_eq(windows[0].source, "b.log")
  assert_eq(windows[0].window.targets, [1])
}
