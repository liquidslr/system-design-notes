import { utf8ArrayToStr } from '@svta/cml-id3';
import { hash } from './hash';
import { toMpegTsClockFromTimescale } from './timescale-conversion';
import { VTTParser } from './vttparser';
import { normalizePts } from '../remux/mp4-remuxer';
import type { TimestampOffset } from './timescale-conversion';
import type { VTTCCs } from '../types/vtt';

const LINEBREAKS = /\r\n|\n\r|\n|\r/g;
const missingInitPTSErrorStartsWith = 'Missing initPTS for VTT ';

const cueString2millis = function (timeString: string) {
  let ts = parseInt(timeString.slice(-3));
  const secs = parseInt(timeString.slice(-6, -4));
  const mins = parseInt(timeString.slice(-9, -7));
  const hours =
    timeString.length > 9
      ? parseInt(timeString.substring(0, timeString.indexOf(':')))
      : 0;

  if (
    !Number.isFinite(ts) ||
    !Number.isFinite(secs) ||
    !Number.isFinite(mins) ||
    !Number.isFinite(hours)
  ) {
    throw Error(`Malformed X-TIMESTAMP-MAP: Local:${timeString}`);
  }

  ts += 1000 * secs;
  ts += 60 * 1000 * mins;
  ts += 60 * 60 * 1000 * hours;

  return ts;
};

// Create a unique hash id for a cue based on start/end times and text.
// This helps timeline-controller to avoid showing repeated captions.
export function generateCueId(
  startTime: number,
  endTime: number,
  text: string,
) {
  return hash(startTime.toString()) + hash(endTime.toString()) + hash(text);
}

export function parseWebVTT(
  vttByteArray: ArrayBuffer,
  initPTS: TimestampOffset | undefined,
  vttCCs: VTTCCs,
  cc: number,
  timeOffset: number,
  callBack: (cues: VTTCue[]) => void,
  errorCallBack: (error: Error) => void,
) {
  const parser = new VTTParser();
  // Convert byteArray into string, replacing any somewhat exotic linefeeds with "\n", then split on that character.
  // Uint8Array.prototype.reduce is not implemented in IE11
  const vttLines = utf8ArrayToStr(new Uint8Array(vttByteArray))
    .trim()
    .replace(LINEBREAKS, '\n')
    .split('\n');
  const cues: VTTCue[] = [];
  const init90kHz = initPTS
    ? toMpegTsClockFromTimescale(initPTS.baseTime, initPTS.timescale)
    : 0;
  let cueTime = '00:00.000';
  let timestampMapMPEGTS = 0;
  let timestampMapLOCAL = 0;
  let hasTimestampMap = false;
  let parsingError: Error | undefined;
  let inHeader = true;

  parser.oncue = function (cue: VTTCue) {
    // Adjust cue timing; clamp cues to start no earlier than - and drop cues that don't end after - 0 on timeline.
    const currCC = vttCCs[cc];
    let cueOffset = vttCCs.ccOffset;

    // Calculate subtitle PTS offset
    const webVttMpegTsMapOffset = (timestampMapMPEGTS - init90kHz) / 90000;

    if (hasTimestampMap) {
      // Update offsets for new discontinuities
      if (currCC?.new) {
        // When local time is provided, offset = discontinuity start time - local time
        cueOffset = vttCCs.ccOffset = currCC.start;
      }
      if (webVttMpegTsMapOffset) {
        if (!initPTS) {
          parsingError = new Error(missingInitPTSErrorStartsWith + 'MPEGTS');
          return;
        }
        // If we have MPEGTS, offset = presentation time + discontinuity offset
        cueOffset = webVttMpegTsMapOffset - vttCCs.presentationOffset;
      }
    } else if (!initPTS) {
      // Without X-TIMESTAMP-MAP, cue time 0 maps to MPEGTS 0 per HLS spec
      parsingError = new Error(
        missingInitPTSErrorStartsWith + 'without X-TIMESTAMP-MAP',
      );
      return;
    } else {
      cueOffset = -initPTS.baseTime / initPTS.timescale;
    }

    const duration = cue.endTime - cue.startTime;
    const startTime =
      normalizePts(
        (cue.startTime + cueOffset - timestampMapLOCAL) * 90000,
        timeOffset * 90000,
      ) / 90000;
    cue.startTime = Math.max(startTime, 0);
    cue.endTime = Math.max(startTime + duration, 0);

    //trim trailing webvtt block whitespaces
    const text = cue.text.trim();

    // Fix encoding of special characters
    cue.text = decodeURIComponent(encodeURIComponent(text));

    // If the cue was not assigned an id from the VTT file (line above the content), create one.
    if (!cue.id) {
      cue.id = generateCueId(cue.startTime, cue.endTime, text);
    } else if (cc) {
      // Prevent same id in cues accross different discontinuities
      cue.id = `hlsjscc${cc}_${cue.id}`;
    }

    if (cue.endTime > 0) {
      cues.push(cue);
    }
  };

  parser.onparsingerror = function (error: Error) {
    parsingError = error;
  };

  parser.onflush = function () {
    if (parsingError) {
      errorCallBack(parsingError);
      return;
    }
    callBack(cues);
  };

  // Go through contents line by line.
  vttLines.forEach((line) => {
    if (inHeader) {
      // Look for X-TIMESTAMP-MAP in header.
      if (line.startsWith('X-TIMESTAMP-MAP=')) {
        // Once found, no more are allowed anyway, so stop searching.
        inHeader = false;
        hasTimestampMap = true;
        // Extract LOCAL and MPEGTS.
        line
          .slice(16)
          .split(',')
          .forEach((timestamp) => {
            if (timestamp.startsWith('LOCAL:')) {
              cueTime = timestamp.slice(6);
            } else if (timestamp.startsWith('MPEGTS:')) {
              timestampMapMPEGTS = parseInt(timestamp.slice(7));
            }
          });
        try {
          // Convert cue time to seconds
          timestampMapLOCAL = cueString2millis(cueTime) / 1000;
        } catch (error) {
          parsingError = error;
        }
        // Return without parsing X-TIMESTAMP-MAP line.
        return;
      } else if (line === '') {
        inHeader = false;
      }
    }
    // Parse line by default.
    parser.parse(line + '\n');
  });

  parser.flush();
}
