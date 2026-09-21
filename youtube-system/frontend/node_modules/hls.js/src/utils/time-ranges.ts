/**
 *  TimeRanges to string helper
 */

export function timeRangesToString(r: TimeRanges) {
  let log = '';
  const len = r.length;
  for (let i = 0; i < len; i++) {
    log += `[${r.start(i).toFixed(3)}-${r.end(i).toFixed(3)}]`;
  }

  return log;
}
