///|
// Bounded evaluation adapter: counts in argv, actual production detector out.
fn main raise {
  let args = @env.args()
  guard args.length() == 7 else {
    abort("algorithm n multiplier min alpha-or-mad comma-counts")
  }
  let detector = match args[1] {
    "moving-average" => @engine.MovingAverage
    "ewma" => @engine.Ewma
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
