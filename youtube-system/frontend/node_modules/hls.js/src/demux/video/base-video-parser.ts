import { appendUint8Array } from '../../utils/mp4-tools';
import type {
  DemuxedUserdataTrack,
  DemuxedVideoTrack,
  VideoSample,
  VideoSampleUnit,
} from '../../types/demuxer';
import type { ChunkMetadata } from '../../types/transmuxer';
import type { ParsedVideoSample } from '../tsdemuxer';
import type { PES } from '../tsdemuxer';

const ANNEX_B_START_CODE_MARKER = 0x01;
const MIN_START_CODE_ZERO_RUN = 2;
const NAL_UNIT_TYPE_PENDING = -1;

abstract class BaseVideoParser {
  protected VideoSample: ParsedVideoSample | null = null;

  protected createVideoSample(
    key: boolean,
    pts: number | undefined,
    dts: number | undefined,
  ): ParsedVideoSample {
    return {
      key,
      frame: false,
      pts,
      dts,
      units: [],
      length: 0,
    };
  }

  protected getLastNalUnit(
    samples: VideoSample[],
  ): VideoSampleUnit | undefined {
    let VideoSample = this.VideoSample;
    let lastUnit: VideoSampleUnit | undefined;
    // try to fallback to previous sample if current one is empty
    if (!VideoSample || VideoSample.units.length === 0) {
      VideoSample = samples[samples.length - 1];
    }
    if (VideoSample?.units) {
      const units = VideoSample.units;
      lastUnit = units[units.length - 1];
    }
    return lastUnit;
  }

  protected pushAccessUnit(
    VideoSample: ParsedVideoSample,
    videoTrack: DemuxedVideoTrack,
  ) {
    if (VideoSample.units.length && VideoSample.frame) {
      // if sample does not have PTS/DTS, patch with last sample PTS/DTS
      if (VideoSample.pts === undefined) {
        const samples = videoTrack.samples;
        const nbSamples = samples.length;
        if (nbSamples) {
          const lastSample = samples[nbSamples - 1];
          VideoSample.pts = lastSample.pts;
          VideoSample.dts = lastSample.dts;
        } else {
          // dropping samples, no timestamp found
          videoTrack.dropped++;
          return;
        }
      }
      videoTrack.samples.push(VideoSample as VideoSample);
    }
  }

  abstract parsePES(
    track: DemuxedVideoTrack,
    textTrack: DemuxedUserdataTrack,
    pes: PES,
    last: boolean,
    chunkMeta?: ChunkMetadata,
  );

  protected abstract getNALuType(data: Uint8Array, offset: number): number;

  protected parseNALu(
    track: DemuxedVideoTrack,
    array: Uint8Array,
    _endOfSegment: boolean,
  ): VideoSampleUnit[] {
    const len = array.byteLength;
    if (len === 0) {
      return [];
    }

    const previousState = track.naluState || 0;
    const previousZeroRun =
      previousState === NAL_UNIT_TYPE_PENDING ? 0 : previousState;

    const units: VideoSampleUnit[] = [];
    let nextState = 0;
    let searchFrom = 0;
    let unitStart = -1;
    let unitType = 0;

    if (previousState === NAL_UNIT_TYPE_PENDING) {
      // A delimiter ended at the preceding chunk boundary.
      unitStart = 0;
      unitType = this.getNALuType(array, 0);
      searchFrom = 1;
    }

    while (searchFrom < len) {
      // Native marker search avoids a JavaScript branch for every payload byte.
      const markerIndex = array.indexOf(ANNEX_B_START_CODE_MARKER, searchFrom);

      if (markerIndex === -1) {
        break;
      }

      searchFrom = markerIndex + 1;

      let nalEnd = markerIndex;
      while (nalEnd > 0 && array[nalEnd - 1] === 0) {
        nalEnd--;
      }

      // The delimiter's zero run may begin in the preceding chunk.
      const zeroRun =
        markerIndex - nalEnd + (nalEnd === 0 ? previousZeroRun : 0);

      if (zeroRun < MIN_START_CODE_ZERO_RUN) {
        continue;
      }

      if (unitStart >= 0) {
        units.push({
          data: array.subarray(unitStart, nalEnd),
          type: unitType,
        });
      } else {
        const previousUnit = this.getLastNalUnit(track.samples);

        if (previousUnit) {
          if (nalEnd > 0) {
            // Bytes before the first delimiter continue the preceding NAL.
            previousUnit.data = appendUint8Array(
              previousUnit.data,
              array.subarray(0, nalEnd),
            );
          } else if (previousZeroRun > 0) {
            previousUnit.data = previousUnit.data.subarray(
              0,
              previousUnit.data.byteLength - previousZeroRun,
            );
          }

          previousUnit.state = 0;
        }
      }

      if (searchFrom < len) {
        unitStart = searchFrom;
        unitType = this.getNALuType(array, searchFrom);
      } else {
        nextState = NAL_UNIT_TYPE_PENDING;
        unitStart = -1;
        break;
      }
    }

    if (nextState !== NAL_UNIT_TYPE_PENDING) {
      let trailingZeroStart = len;

      while (trailingZeroStart > 0 && array[trailingZeroStart - 1] === 0) {
        trailingZeroStart--;
      }

      nextState =
        len -
        trailingZeroStart +
        (trailingZeroStart === 0 ? previousZeroRun : 0);
    }

    if (unitStart >= 0) {
      units.push({
        data: array.subarray(unitStart),
        type: unitType,
        state: nextState,
      });
    } else if (units.length === 0 && nextState !== NAL_UNIT_TYPE_PENDING) {
      const previousUnit = this.getLastNalUnit(track.samples);

      if (previousUnit) {
        previousUnit.data = appendUint8Array(previousUnit.data, array);
        previousUnit.state = nextState;
      }
    }

    track.naluState = nextState;
    return units;
  }
}

export default BaseVideoParser;
