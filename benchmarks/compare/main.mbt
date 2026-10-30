///|
fn main raise {
  let args = @env.args()
  let mode = if args.length() > 2 { args[2] } else { "full" }
  guard ["full", "read", "digest", "parse", "aggregate"].contains(mode) else {
    abort("unknown profiling mode")
  }
  if mode != "full" {
    let digest = @engine.Sha256::new()
    let analyzer = @engine.Analyzer::new(@engine.Config::new())
    let mut lines = 0L
    let mut timed = 0L
    for _ in 0..<2 {
      @io.each_line(
        args[1],
        raw => {
          lines += 1L
          if mode == "parse" {
            let record = @engine.parse_line(raw)
            if record.minute is Some(_) {
              timed += 1L
            }
          } else if mode == "aggregate" {
            analyzer.feed(raw)
          }
        },
        observe_chunk=bytes => if mode == "digest" { digest.feed_bytes(bytes) },
      )
    }
    if mode == "aggregate" {
      ignore(analyzer.finish())
    }
    println("\{lines} \{timed} \{digest.hex()}")
    return
  }
  let a = @engine.Analyzer::new(@engine.Config::new())
  let digests : Array[String] = []
  for pass in 0..<2 {
    let digest = @engine.Sha256::new()
    @io.each_line(
      args[1],
      raw => {
        if pass == 0 {
          a.feed(raw)
        } else {
          ignore(@engine.parse_line(raw))
        }
      },
      observe_chunk=bytes => digest.feed_bytes(bytes),
    )
    digests.push(digest.hex())
  }
  guard digests[0] == digests[1] else { abort("input changed") }
  let result = a.finish()
  let levels : Map[String, Json] = Map([])
  for key in ["DEBUG", "INFO", "WARN", "ERROR", "FATAL", "OTHER"] {
    levels[key] = Json(result.counts.get_or_default(key, 0L).to_double())
  }
  println(
    Json::object({
      "total": Json(result.total.to_double()),
      "untimed": Json(result.untimed.to_double()),
      "levels": Json::object(levels),
      "sha256": Json(digests[0]),
      "buckets": Json::array(
        result.buckets.map(b => {
          Json::array([
            Json(b.start.to_double()),
            Json(b.total.to_double()),
            Json(b.errors.to_double()),
          ])
        }),
      ),
      "signatures": Json::array(
        result.signatures.map(s => {
          Json::array([Json(s.text), Json(s.count.to_double())])
        }),
      ),
      "spikes": Json::array(
        result.spikes.map(s => {
          Json::array([
            Json(s.start.to_double()),
            Json(s.end.to_double()),
            Json(s.errors.to_double()),
            Json(s.peak_errors.to_double()),
            Json(s.baseline),
          ])
        }),
      ),
    }).stringify(),
  )
}
