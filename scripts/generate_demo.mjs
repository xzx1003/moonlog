// Deterministic synthetic demo. Not production data or a root-cause claim.
import { writeFileSync } from 'node:fs';
const rows = [];
const incidents = [
  { start: 40, warn: 'database pool usage above threshold', errors: [
    ['ERROR', 'database query timeout duration_ms=3000 request_id=101'],
    ['ERROR', 'connection pool exhausted active=32 waiting=18'],
    ['ERROR', 'transaction deadlock retry=2'],
  ], recovery: 'database pool recovered; transaction retries succeeded' },
  { start: 120, warn: 'upstream latency rising; retry budget nearly exhausted', errors: [
    ['ERROR', 'upstream connection refused host=inventory.local port=8080'],
    ['ERROR', 'HTTP 503 service unavailable route=/checkout request_id=202'],
    ['ERROR', 'TLS certificate expired host=payments.local'],
  ], recovery: 'upstream available; certificate replaced; circuit breaker closed' },
  { start: 200, warn: 'worker memory high; disk free space low', errors: [
    ['FATAL', 'worker out of memory worker=7 allocation_bytes=1048576'],
    ['ERROR', 'disk write failed: no space left on device path=/var/log/app'],
    ['ERROR', 'unhandled exception: TypeError cannot read property order_id'],
  ], recovery: 'worker restarted; disk cleanup completed; requests resumed' },
];
for (let minute = 0; minute < 240; minute++) {
  const ts = `2026-10-28 ${String(8 + Math.floor(minute / 60)).padStart(2,'0')}:${String(minute % 60).padStart(2,'0')}:00`;
  const add = (level, msg, json = false) => rows.push(json ? JSON.stringify({ts, level, msg}) : `${ts} [${level}] ${msg}`);
  if (minute === 0) add('INFO','SYNTHETIC DEMO: independent fault examples; messages do not prove causality');
  add('INFO',`request completed status=200 request_id=${minute}`);
  if (minute % 10 === 0) add('DEBUG', `cache hit key=item-${minute}`);
  if (minute % 30 === 0) add('WARN', 'authentication rejected status=401 route=/admin (background warning)');
  // One background error per 30 minutes, below the default spike minimum.
  if (minute % 30 === 10) add('ERROR', 'scheduled export failed: permission denied path=/exports/daily');
  if (minute === 15) rows.push(`${ts} [NOTICE] deployment marker version=2`);
  for (const [index, incident] of incidents.entries()) {
    if (minute === incident.start - 1) add('WARN', incident.warn, index === 1);
    if (minute >= incident.start && minute < incident.start + 5) {
      for (const [level, message] of incident.errors) add(level, message, index === 1);
      if (index === 2 && minute === incident.start) rows.push('    at processOrder (orders.mbt:42)', '    at runWorker (worker.mbt:18)');
    }
    if (minute === incident.start + 5) add('INFO', incident.recovery, index === 1);
  }
}
writeFileSync(new URL('../web/sample.log', import.meta.url), rows.join('\n') + '\n');
console.log(`${rows.length} synthetic physical lines generated`);
