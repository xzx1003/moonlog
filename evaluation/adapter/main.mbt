///|
// Bounded evaluation adapter: counts in argv, actual production detector out.
fn main raise {
  let args = @env.args()
  guard args.length() == 7 else {
    abort("algorithm n multiplier min alpha-or-mad comma-counts")
  }
  let detector = match args[1] {
    "moving-average" => @engine.MovingAverage
    "ewma" | "ewma-freeze" => @engine.Ewma
    "mad" => @engine.Mad
    _ => abort("unknown algorithm")
  }
  let n = @string.parse_int(args[2])
  let multiplier = @string.parse_int(args[3])
  let minimum = @string.parse_int(args[4])
  // Evaluation grids use integer tenths for floating parameters.
  let parameter = @string.parse_int(args[5]).to_double() / 10.0
  let config = @engine.Config::new(
    detector~,
    baseline_buckets=n,
    multiplier~,
    min_errors=minimum,
    ewma_alpha=if detector == @engine.Ewma { parameter } else { 0.3 },
    mad_threshold=if detector == @engine.Mad { parameter } else { 3.0 },
  )
  let buckets : Array[@engine.Bucket] = []
  for i, text in args[6].split(",").to_array() {
    let errors = @string.parse_int(text)
    guard errors >= 0 else { abort("negative count") }
    buckets.push({
      start: i.to_int64() * 5L,
      total: errors.to_int64(),
      errors: errors.to_int64(),
    })
  }
  if args[1] == "ewma-freeze" {
    let mut baseline = 0.0
    for i in 0..<n.min(buckets.length()) {
      baseline += buckets[i].errors.to_double() / n.to_double()
    }
    let rows : Array[Json] = []
    for i in n..<buckets.length() {
      let value = buckets[i].errors.to_double()
      let threshold = baseline * multiplier.to_double()
      let hit = buckets[i].errors >= minimum.to_int64() && value > threshold
      rows.push(
        Json::array([Json(i), Json(baseline), Json(threshold), Json(hit)]),
      )
      if !hit {
        baseline = parameter * value + (1.0 - parameter) * baseline
      }
    }
    println(Json::array(rows).stringify())
    return
  }
  let spikes = @engine.detect_spikes(buckets, config)
  println(
    Json::array(
      spikes.map(s => {
        Json::array([
          Json(s.start.to_double()),
          Json(s.end.to_double()),
          Json(s.errors.to_double()),
          Json(s.baseline),
        ])
      }),
    ).stringify(),
  )
}
