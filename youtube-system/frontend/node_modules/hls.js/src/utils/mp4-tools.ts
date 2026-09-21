import { utf8ArrayToStr } from '@svta/cml-id3';
import { arrayToHex } from './hex';
import { bin2str } from './numeric-encoding-utils';
import { ElementaryStreamTypes } from '../loader/fragment';
import { logger } from '../utils/logger';
import type { ChunkMetadata } from '../hls';
import type { KeySystemIds } from './mediakeys-helper';
import type { DecryptData } from '../loader/level-key';
import type { PassthroughTrack, UserdataSample } from '../types/demuxer';
import type { ILogger } from '../utils/logger';

type BoxDataOrUndefined = Uint8Array<ArrayBuffer> | undefined;

export const UINT32_MAX = Math.pow(2, 32) - 1;

export const types = {
  avc1: 0x61766331,
  avcC: 0x61766343,
  hvc1: 0x68766331,
  hvcC: 0x68766343,
  btrt: 0x62747274,
  dinf: 0x64696e66,
  dref: 0x64726566,
  esds: 0x65736473,
  free: 0x66726565,
  ftyp: 0x66747970,
  hdlr: 0x68646c72,
  mdat: 0x6d646174,
  mdhd: 0x6d646864,
  mdia: 0x6d646961,
  mfhd: 0x6d666864,
  minf: 0x6d696e66,
  moof: 0x6d6f6f66,
  moov: 0x6d6f6f76,
  mp4a: 0x6d703461,
  '.mp3': 0x2e6d7033,
  dac3: 0x64616333,
  'ac-3': 0x61632d33,
  mvex: 0x6d766578,
  mvhd: 0x6d766864,
  pasp: 0x70617370,
  sdtp: 0x73647470,
  stbl: 0x7374626c,
  stco: 0x7374636f,
  stsc: 0x73747363,
  stsd: 0x73747364,
  stsz: 0x7374737a,
  stts: 0x73747473,
  tfdt: 0x74666474,
  tfhd: 0x74666864,
  traf: 0x74726166,
  trak: 0x7472616b,
  trun: 0x7472756e,
  trex: 0x74726578,
  tkhd: 0x746b6864,
  vmhd: 0x766d6864,
  smhd: 0x736d6864,
} as const;

type BoxType = keyof typeof types;

// We are using fixed track IDs for driving the MP4 remuxer
// instead of following the TS PIDs.
// There is no reason not to do this and some browsers/SourceBuffer-demuxers
// may not like if there are TrackID "switches"
// See https://github.com/video-dev/hls.js/issues/1331
// Here we are mapping our internal track types to constant MP4 track IDs
// With MSE currently one can only have one track of each, and we are muxing
// whatever video/audio rendition in them.
export const RemuxerTrackIdConfig = {
  video: 1,
  audio: 2,
  id3: 3,
  text: 4,
};

function readUint16(buffer: Uint8Array, offset: number): number {
  const val = (buffer[offset] << 8) | buffer[offset + 1];
  return val < 0 ? 65536 + val : val;
}

function readUint32(buffer: Uint8Array, offset: number): number {
  const val =
    (buffer[offset] << 24) |
    (buffer[offset + 1] << 16) |
    (buffer[offset + 2] << 8) |
    buffer[offset + 3];
  return val < 0 ? 4294967296 + val : val;
}

function readUint64(buffer: Uint8Array, offset: number) {
  let result = readUint32(buffer, offset);
  result *= Math.pow(2, 32);
  result += readUint32(buffer, offset + 4);
  return result;
}

// Returns a null-terminated string including its terminator, or null when the
// buffer ends before the terminator. Callers advance by the returned length;
// an unterminated string consumes the rest of the buffer.
function readCString(buffer: Uint8Array, offset: number): string | null {
  let result = '';
  for (let i = offset; i < buffer.length; i++) {
    result += String.fromCharCode(buffer[i]);
    if (buffer[i] === 0) {
      return result;
    }
  }
  return null;
}

function readSint32(buffer: Uint8Array, offset: number): number {
  return (
    (buffer[offset] << 24) |
    (buffer[offset + 1] << 16) |
    (buffer[offset + 2] << 8) |
    buffer[offset + 3]
  );
}

export function writeUint32(buffer: Uint8Array, offset: number, value: number) {
  buffer[offset] = value >> 24;
  buffer[offset + 1] = (value >> 16) & 0xff;
  buffer[offset + 2] = (value >> 8) & 0xff;
  buffer[offset + 3] = value & 0xff;
}

// Shrink a box to newPayloadSize + header, turning the remainder into a
// nested 'free' box (Safari rejects trun/saiz boxes larger than their
// declared sample count requires)
function shrinkBox(data: Uint8Array, box: Uint8Array, newPayloadSize: number) {
  const start = box.byteOffset - data.byteOffset - 8;
  const newSize = 8 + newPayloadSize;
  const tail = box.byteLength + 8 - newSize;
  if (tail < 8) {
    // No change needed, or the remainder is too small to hold a box header
    return;
  }
  writeUint32(data, start, newSize);
  writeUint32(data, start + newSize, tail);
  writeUint32(data, start + newSize + 4, types.free);
}

// View-relative [start, end) byte range of a box, including its 8-byte header
function boxRange(box: Uint8Array, base: number): [number, number] {
  return [box.byteOffset - base - 8, box.byteOffset - base + box.byteLength];
}

// Splice the given byte ranges out of `data`, returning the shrunk copy, the
// total bytes removed, and a droppedBefore(offset) helper for repositioning
// surviving offsets. Ranges are view-relative and sorted in place.
function spliceOutBoxes(
  data: Uint8Array<ArrayBuffer>,
  dropRanges: [number, number][],
): {
  result: Uint8Array<ArrayBuffer>;
  dropped: number;
  droppedBefore: (offset: number) => number;
} {
  dropRanges.sort((a, b) => a[0] - b[0]);
  const dropped = dropRanges.reduce(
    (sum, [start, end]) => sum + end - start,
    0,
  );
  const result = new Uint8Array(data.byteLength - dropped);
  let read = 0;
  let write = 0;
  for (let i = 0; i < dropRanges.length; i++) {
    const [start, end] = dropRanges[i];
    result.set(data.subarray(read, start), write);
    write += start - read;
    read = end;
  }
  result.set(data.subarray(read), write);
  const droppedBefore = (offset: number) =>
    dropRanges.reduce(
      (sum, [start, end]) => (end <= offset ? sum + end - start : sum),
      0,
    );
  return { result, dropped, droppedBefore };
}

// Video-only copy of an init segment, or null when there is no video track or nothing to remove
export function videoOnlyInitSegment(
  initSegment: Uint8Array<ArrayBuffer>,
): Uint8Array<ArrayBuffer> | null {
  const moovs = findBox(initSegment, ['moov']);
  if (moovs.length !== 1 || findBox(initSegment, ['moof']).length) {
    return null;
  }
  const base = initSegment.byteOffset;
  const dropRanges: [number, number][] = [];
  const dropTrackIds: number[] = [];
  let hasVideo = false;
  const traks = findBox(moovs[0], ['trak']);
  for (let i = 0; i < traks.length; i++) {
    const trak = traks[i];
    const hdlr = findBox(trak, ['mdia', 'hdlr'])[0];
    const handler = hdlr ? bin2str(hdlr.subarray(8, 12)) : '';
    if (handler === 'vide') {
      hasVideo = true;
      continue;
    }
    const tkhd = findBox(trak, ['tkhd'])[0];
    if (!tkhd) {
      return null;
    }
    const version = tkhd[0];
    dropTrackIds.push(readUint32(tkhd, version === 0 ? 12 : 20));
    dropRanges.push(boxRange(trak, base));
  }
  if (!hasVideo || !dropRanges.length) {
    return null;
  }
  const mvex = findBox(moovs[0], ['mvex'])[0];
  let mvexDropped = 0;
  if (mvex) {
    const trexs = findBox(mvex, ['trex']);
    for (let i = 0; i < trexs.length; i++) {
      const trex = trexs[i];
      if (dropTrackIds.indexOf(readUint32(trex, 4)) !== -1) {
        dropRanges.push(boxRange(trex, base));
        mvexDropped += trex.byteLength + 8;
      }
    }
  }
  // Splice out the dropped ranges, then patch sizes at their result offsets
  const { result, dropped, droppedBefore } = spliceOutBoxes(
    initSegment,
    dropRanges,
  );
  const moovStart = moovs[0].byteOffset - base - 8;
  writeUint32(result, moovStart, moovs[0].byteLength + 8 - dropped);
  if (mvex && mvexDropped) {
    const mvexStart = mvex.byteOffset - base - 8;
    writeUint32(
      result,
      mvexStart - droppedBefore(mvexStart),
      mvex.byteLength + 8 - mvexDropped,
    );
  }
  return result;
}

// Duration rewrite for remuxVideoOnlyIFrameMoof: `value` (video timescale) is
// written at `durationOffset` — the last sample's duration or the tfhd default
export type IFrameDurationRewrite = {
  durationOffset: number;
  value: number;
};

// Remux a moof+mdat I-Frame fragment to video-only in place: drop non-video trafs
// (muxed A/V), truncate to the in-range samples (partial mdat), and stretch the
// last sample duration, preserving senc/saiz/saio. Returns null when it cannot be
// rewritten (no video traf, no samples, or non-moof-relative muxed content).
export function remuxVideoOnlyIFrameMoof(
  data: Uint8Array<ArrayBuffer>,
  videoTrackId: number,
  keepSampleCount: number,
  keepEndOffset: number | undefined,
  durationRewrite: IFrameDurationRewrite | undefined,
): Uint8Array<ArrayBuffer> | null {
  if (keepSampleCount < 1) {
    return null;
  }
  const moofs = findBox(data, ['moof']);
  if (moofs.length !== 1) {
    return null;
  }
  const moof = moofs[0];
  const base = data.byteOffset;
  const videoTrafs: Uint8Array[] = [];
  const dropRanges: [number, number][] = [];
  const trafs = findBox(moof, ['traf']);
  let videoBaseIsMoof = true;
  for (let i = 0; i < trafs.length; i++) {
    const traf = trafs[i];
    const tfhd = findBox(traf, ['tfhd'])[0];
    if (!tfhd) {
      return null;
    }
    if (readUint32(tfhd, 4) === videoTrackId) {
      videoTrafs.push(traf);
      if (!(readUint32(tfhd, 0) & 0x20000)) {
        videoBaseIsMoof = false;
      }
    } else {
      dropRanges.push(boxRange(traf, base));
    }
  }
  if (!videoTrafs.length) {
    return null;
  }
  // Patching moof-relative offsets after a splice requires default-base-is-moof
  if (dropRanges.length && !videoBaseIsMoof) {
    return null;
  }

  if (keepEndOffset !== undefined) {
    // Distribute the kept count across the runs; emptied runs become 'free'
    // boxes (parsers reject zero-sample truns)
    let remaining = keepSampleCount;
    for (let t = 0; t < videoTrafs.length; t++) {
      const traf = videoTrafs[t];
      let trafKept = 0;
      const truns = findBox(traf, ['trun']);
      for (let j = 0; j < truns.length; j++) {
        const trun = truns[j];
        const count = Math.min(remaining, readUint32(trun, 4));
        if (count) {
          writeUint32(data, trun.byteOffset - base + 4, count);
          const flags = readUint32(trun, 0) & 0xffffff;
          const perSample =
            (flags & 0x100 ? 4 : 0) +
            (flags & 0x200 ? 4 : 0) +
            (flags & 0x400 ? 4 : 0) +
            (flags & 0x800 ? 4 : 0);
          shrinkBox(
            data,
            trun,
            8 +
              (flags & 0x01 ? 4 : 0) +
              (flags & 0x04 ? 4 : 0) +
              count * perSample,
          );
        } else {
          writeUint32(data, trun.byteOffset - base - 4, types.free);
        }
        remaining -= count;
        trafKept += count;
      }
      const senc = findBox(traf, ['senc'])[0];
      if (senc) {
        // The size of a senc box cannot be validated without the tenc IV size,
        // so rewriting the sample count alone is accepted
        writeUint32(data, senc.byteOffset - base + 4, trafKept);
      }
      const saiz = findBox(traf, ['saiz'])[0];
      if (saiz) {
        const saizFlags = (saiz[1] << 16) | (saiz[2] << 8) | saiz[3];
        let off = 4;
        if (saizFlags & 0x01) {
          off += 8;
        }
        const defaultSampleInfoSize = saiz[off];
        off += 1;
        writeUint32(data, saiz.byteOffset - base + off, trafKept);
        shrinkBox(
          data,
          saiz,
          off + 4 + (defaultSampleInfoSize === 0 ? trafKept : 0),
        );
      }
    }
    const mdats = findBox(data, ['mdat']);
    if (mdats.length === 1) {
      const mdatStart = mdats[0].byteOffset - base - 8;
      writeUint32(data, mdatStart, keepEndOffset - mdatStart);
    }
  }

  let result: Uint8Array<ArrayBuffer> = data;
  let dropped = 0;
  let droppedBefore: (offset: number) => number = () => 0;
  if (dropRanges.length) {
    // Splice out the dropped ranges, then patch sizes/offsets at their result offsets
    ({ result, dropped, droppedBefore } = spliceOutBoxes(data, dropRanges));
    writeUint32(
      result,
      moof.byteOffset - base - 8,
      moof.byteLength + 8 - dropped,
    );
    for (let t = 0; t < videoTrafs.length; t++) {
      const traf = videoTrafs[t];
      // The mdat moves up by everything dropped; the traf and the senc payload
      // its saio points to by what was dropped before the traf
      const trafShift = droppedBefore(traf.byteOffset - base);
      const truns = findBox(traf, ['trun']);
      for (let j = 0; j < truns.length; j++) {
        const trun = truns[j];
        if (readUint32(trun, 0) & 0x01) {
          writeUint32(
            result,
            trun.byteOffset - base - trafShift + 8,
            readUint32(trun, 8) - dropped,
          );
        }
      }
      if (trafShift) {
        const saios = findBox(traf, ['saio']);
        for (let s = 0; s < saios.length; s++) {
          const saio = saios[s];
          const stride = saio[0] === 0 ? 4 : 8;
          let offset = readUint32(saio, 0) & 0x01 ? 12 : 4;
          let entries = readUint32(saio, offset);
          for (offset += 4; entries--; offset += stride) {
            // Patch the low word of each aux info offset
            const at = offset + stride - 4;
            writeUint32(
              result,
              saio.byteOffset - base - trafShift + at,
              readUint32(saio, at) - trafShift,
            );
          }
        }
      }
    }
  }

  if (durationRewrite) {
    const { durationOffset, value } = durationRewrite;
    writeUint32(result, durationOffset - droppedBefore(durationOffset), value);
  }

  return keepEndOffset !== undefined
    ? result.subarray(0, keepEndOffset - dropped)
    : result;
}

export function hasBoxData(data: Uint8Array, type: BoxType): boolean {
  const end = data.byteLength;
  for (let i = 0; i < end; ) {
    const size = readUint32(data, i);
    if (size > 8 && readUint32(data, i + 4) === types[type]) {
      return true;
    }
    i = size > 1 ? i + size : end;
  }
  return false;
}

// Find the data for a box specified by its path
export function findBox(data: Uint8Array, path: string[]): Uint8Array[] {
  const results = [] as Uint8Array[];
  if (!path.length) {
    // short-circuit the search for empty paths
    return results;
  }
  findBoxPath(data, path, 0, 0, data.byteLength, results);
  return results;
}

function findBoxPath(
  data: Uint8Array,
  path: string[],
  pathIndex: number,
  start: number,
  end: number,
  results: Uint8Array[],
): void {
  const pathType = path[pathIndex];
  if (pathType?.length !== 4) {
    return;
  }
  const type0 = pathType.charCodeAt(0);
  const type1 = pathType.charCodeAt(1);
  const type2 = pathType.charCodeAt(2);
  const type3 = pathType.charCodeAt(3);
  const lastPathIndex = path.length - 1;

  for (let i = start; i < end; ) {
    const hasHeader = i + 8 <= end;
    const size =
      i + 4 <= end
        ? data[i] * 0x1000000 +
          ((data[i + 1] << 16) | (data[i + 2] << 8) | data[i + 3])
        : readUint32(data, i);
    const endbox = size > 1 ? i + size : end;
    if (
      hasHeader &&
      data[i + 4] === type0 &&
      data[i + 5] === type1 &&
      data[i + 6] === type2 &&
      data[i + 7] === type3
    ) {
      const boxEnd = Math.min(endbox, end);
      if (pathIndex === lastPathIndex) {
        // this is the end of the path and we've found the box we were
        // looking for
        results.push(data.subarray(i + 8, boxEnd));
      } else {
        // recursively search for the next box along the path
        findBoxPath(data, path, pathIndex + 1, i + 8, boxEnd, results);
      }
    }
    i = endbox;
  }
}

type SidxInfo = {
  earliestPresentationTime: number;
  timescale: number;
  version: number;
  referencesCount: number;
  references: any[];
};

function parseSegmentIndex(sidx: Uint8Array): SidxInfo | null {
  const references: any[] = [];

  const version = sidx[0];

  // set initial offset, we skip the reference ID (not needed)
  let index = 8;

  const timescale = readUint32(sidx, index);
  index += 4;

  let earliestPresentationTime = 0;
  let firstOffset = 0;

  if (version === 0) {
    earliestPresentationTime = readUint32(sidx, index);
    firstOffset = readUint32(sidx, index + 4);
    index += 8;
  } else {
    earliestPresentationTime = readUint64(sidx, index);
    firstOffset = readUint64(sidx, index + 8);
    index += 16;
  }

  // skip reserved
  index += 2;

  let startByte = sidx.length + firstOffset;

  const referencesCount = readUint16(sidx, index);
  index += 2;

  for (let i = 0; i < referencesCount; i++) {
    let referenceIndex = index;

    const referenceInfo = readUint32(sidx, referenceIndex);
    referenceIndex += 4;

    const referenceSize = referenceInfo & 0x7fffffff;
    const referenceType = (referenceInfo & 0x80000000) >>> 31;

    if (referenceType === 1) {
      logger.warn('SIDX has hierarchical references (not supported)');
      return null;
    }

    const subsegmentDuration = readUint32(sidx, referenceIndex);
    referenceIndex += 4;

    references.push({
      referenceSize,
      subsegmentDuration, // unscaled
      info: {
        duration: subsegmentDuration / timescale,
        start: startByte,
        end: startByte + referenceSize - 1,
      },
    });

    startByte += referenceSize;

    // Skipping 1 bit for |startsWithSap|, 3 bits for |sapType|, and 28 bits
    // for |sapDelta|.
    referenceIndex += 4;

    // skip to next ref
    index = referenceIndex;
  }

  return {
    earliestPresentationTime,
    timescale,
    version,
    referencesCount,
    references,
  };
}

/**
 * Parses an MP4 initialization segment and extracts stream type and
 * timescale values for any declared tracks. Timescale values indicate the
 * number of clock ticks per second to assume for time-based values
 * elsewhere in the MP4.
 *
 * To determine the start time of an MP4, you need two pieces of
 * information: the timescale unit and the earliest base media decode
 * time. Multiple timescales can be specified within an MP4 but the
 * base media decode time is always expressed in the timescale from
 * the media header box for the track:
 * ```
 * moov > trak > mdia > mdhd.timescale
 * moov > trak > mdia > hdlr
 * ```
 * @param initSegment the bytes of the init segment
 * @returns a hash of track type to timescale values or null if
 * the init segment is malformed.
 */

export interface InitDataTrack {
  timescale: number;
  id: number;
  codec: string;
  encrypted: boolean;
  supplemental: string | undefined;
}

type HdlrMetadata = 'meta';
type HdlrType =
  | ElementaryStreamTypes.AUDIO
  | ElementaryStreamTypes.VIDEO
  | HdlrMetadata;

type StsdData = {
  codec: string;
  encrypted: boolean;
  supplemental: string | undefined;
};

export interface InitData extends Array<any> {
  [index: number]:
    | {
        timescale: number;
        type: HdlrType;
        stsd: StsdData;
        default?: {
          duration: number;
          sampleSize: number;
          flags: number;
        };
      }
    | undefined;
  audio?: InitDataTrack;
  video?: InitDataTrack;
  caption?: InitDataTrack;
}

export function parseInitSegment(initSegment: Uint8Array): InitData {
  const result: InitData = [];
  const traks = findBox(initSegment, ['moov', 'trak']);
  for (let i = 0; i < traks.length; i++) {
    const trak = traks[i];
    const tkhd = findBox(trak, ['tkhd'])[0];
    if (tkhd as any) {
      let version = tkhd[0];
      const trackId = readUint32(tkhd, version === 0 ? 12 : 20);
      const mdhd = findBox(trak, ['mdia', 'mdhd'])[0];
      if (mdhd as any) {
        version = mdhd[0];
        const timescale = readUint32(mdhd, version === 0 ? 12 : 20);
        const hdlr = findBox(trak, ['mdia', 'hdlr'])[0];
        if (hdlr as any) {
          const hdlrType = bin2str(hdlr.subarray(8, 12));
          const type: HdlrType | undefined = {
            soun: ElementaryStreamTypes.AUDIO as const,
            vide: ElementaryStreamTypes.VIDEO as const,
          }[hdlrType];
          // Parse codec details
          const stsdBox = findBox(trak, ['mdia', 'minf', 'stbl', 'stsd'])[0];
          const stsd = parseStsd(stsdBox);
          if (type) {
            // Add 'audio', 'video', and 'audiovideo' track records that will map to SourceBuffers
            result[trackId] = { timescale, type, stsd };
            result[type] = { timescale, id: trackId, ...stsd };
          } else {
            // Add 'meta' and other track records
            result[trackId] = {
              timescale,
              type: hdlrType as HdlrType,
              stsd,
            };
          }
        }
      }
    }
  }

  const trex = findBox(initSegment, ['moov', 'mvex', 'trex']);
  trex.forEach((trex) => {
    const trackId = readUint32(trex, 4);
    const track = result[trackId];
    if (track) {
      track.default = {
        duration: readUint32(trex, 12),
        sampleSize: readUint32(trex, 16),
        flags: readUint32(trex, 20),
      };
    }
  });

  return result;
}

function parseStsd(stsd: Uint8Array): StsdData {
  const sampleEntries = stsd.subarray(8);
  const sampleEntriesEnd = sampleEntries.subarray(8 + 78);
  const fourCC = bin2str(sampleEntries.subarray(4, 8));
  let codec = fourCC;
  let supplemental;
  const encrypted = fourCC === 'enca' || fourCC === 'encv';
  if (encrypted) {
    const encBox = findBox(sampleEntries, [fourCC])[0];
    const encBoxChildren = encBox.subarray(fourCC === 'enca' ? 28 : 78);
    const sinfs = findBox(encBoxChildren, ['sinf']);
    sinfs.forEach((sinf) => {
      const schm = findBox(sinf, ['schm'])[0];
      if (schm as any) {
        const scheme = bin2str(schm.subarray(4, 8));
        if (scheme === 'cbcs' || scheme === 'cenc') {
          const frma = findBox(sinf, ['frma'])[0];
          if (frma as any) {
            // for encrypted content codec fourCC will be in frma
            codec = bin2str(frma);
          }
        }
      }
    });
  }
  const codecFourCC = codec;
  switch (codec) {
    case 'avc1':
    case 'avc2':
    case 'avc3':
    case 'avc4': {
      // extract profile + compatibility + level out of avcC box
      const avcCBox = findBox(sampleEntriesEnd, ['avcC'])[0];
      if ((avcCBox as any) && avcCBox.length > 3) {
        codec +=
          '.' + toHex(avcCBox[1]) + toHex(avcCBox[2]) + toHex(avcCBox[3]);
        supplemental = parseSupplementalDoViCodec(
          codecFourCC === 'avc1' ? 'dva1' : 'dvav',
          sampleEntriesEnd,
        );
      }
      break;
    }
    case 'mp4a': {
      const codecBox = findBox(sampleEntries, [fourCC])[0];
      const esdsBox = findBox(codecBox.subarray(28), ['esds'])[0];
      if ((esdsBox as any) && esdsBox.length > 7) {
        let i = 4;
        // ES Descriptor tag
        if (esdsBox[i++] !== 0x03) {
          break;
        }
        i = skipBERInteger(esdsBox, i);
        i += 2; // skip es_id;
        const flags = esdsBox[i++];
        if (flags & 0x80) {
          i += 2; // skip dependency es_id
        }
        if (flags & 0x40) {
          i += esdsBox[i++]; // skip URL
        }
        // Decoder config descriptor
        if (esdsBox[i++] !== 0x04) {
          break;
        }
        i = skipBERInteger(esdsBox, i);
        const objectType = esdsBox[i++];
        if (objectType === 0x40) {
          codec += '.' + toHex(objectType);
        } else {
          break;
        }
        i += 12;
        // Decoder specific info
        if (esdsBox[i++] !== 0x05) {
          break;
        }
        i = skipBERInteger(esdsBox, i);
        const firstByte = esdsBox[i++];
        let audioObjectType = (firstByte & 0xf8) >> 3;
        if (audioObjectType === 31) {
          audioObjectType +=
            1 + ((firstByte & 0x7) << 3) + ((esdsBox[i] & 0xe0) >> 5);
        }
        codec += '.' + audioObjectType;
      }
      break;
    }
    case 'hvc1':
    case 'hev1': {
      const hvcCBox = findBox(sampleEntriesEnd, ['hvcC'])[0];
      if ((hvcCBox as any) && hvcCBox.length > 12) {
        const profileByte = hvcCBox[1];
        const profileSpace = ['', 'A', 'B', 'C'][profileByte >> 6];
        const generalProfileIdc = profileByte & 0x1f;
        const profileCompat = readUint32(hvcCBox, 2);
        const tierFlag = (profileByte & 0x20) >> 5 ? 'H' : 'L';
        const levelIDC = hvcCBox[12];
        const constraintIndicator = hvcCBox.subarray(6, 12);
        codec += '.' + profileSpace + generalProfileIdc;
        codec +=
          '.' + reverse32BitInt(profileCompat).toString(16).toUpperCase();
        codec += '.' + tierFlag + levelIDC;
        let constraintString = '';
        for (let i = constraintIndicator.length; i--; ) {
          const byte = constraintIndicator[i];
          if (byte || constraintString) {
            const encodedByte = byte.toString(16).toUpperCase();
            constraintString = '.' + encodedByte + constraintString;
          }
        }
        codec += constraintString;
      }
      supplemental = parseSupplementalDoViCodec(
        codecFourCC == 'hev1' ? 'dvhe' : 'dvh1',
        sampleEntriesEnd,
      );
      break;
    }
    case 'dvh1':
    case 'dvhe':
    case 'dvav':
    case 'dva1':
    case 'dav1': {
      codec = parseSupplementalDoViCodec(codec, sampleEntriesEnd) || codec;
      break;
    }
    case 'vp09': {
      const vpcCBox = findBox(sampleEntriesEnd, ['vpcC'])[0];
      if ((vpcCBox as any) && vpcCBox.length > 6) {
        const profile = vpcCBox[4];
        const level = vpcCBox[5];
        const bitDepth = (vpcCBox[6] >> 4) & 0x0f;
        codec +=
          '.' +
          addLeadingZero(profile) +
          '.' +
          addLeadingZero(level) +
          '.' +
          addLeadingZero(bitDepth);
      }
      break;
    }
    case 'av01': {
      const av1CBox = findBox(sampleEntriesEnd, ['av1C'])[0];
      if ((av1CBox as any) && av1CBox.length > 2) {
        const profile = av1CBox[1] >>> 5;
        const level = av1CBox[1] & 0x1f;
        const tierFlag = av1CBox[2] >>> 7 ? 'H' : 'M';
        const highBitDepth = (av1CBox[2] & 0x40) >> 6;
        const twelveBit = (av1CBox[2] & 0x20) >> 5;
        const bitDepth =
          profile === 2 && highBitDepth
            ? twelveBit
              ? 12
              : 10
            : highBitDepth
              ? 10
              : 8;
        const monochrome = (av1CBox[2] & 0x10) >> 4;
        const chromaSubsamplingX = (av1CBox[2] & 0x08) >> 3;
        const chromaSubsamplingY = (av1CBox[2] & 0x04) >> 2;
        const chromaSamplePosition = av1CBox[2] & 0x03;
        // TODO: parse color_description_present_flag
        // default it to BT.709/limited range for now
        // more info https://aomediacodec.github.io/av1-isobmff/#av1codecconfigurationbox-syntax
        const colorPrimaries = 1;
        const transferCharacteristics = 1;
        const matrixCoefficients = 1;
        const videoFullRangeFlag = 0;
        codec +=
          '.' +
          profile +
          '.' +
          addLeadingZero(level) +
          tierFlag +
          '.' +
          addLeadingZero(bitDepth) +
          '.' +
          monochrome +
          '.' +
          chromaSubsamplingX +
          chromaSubsamplingY +
          chromaSamplePosition +
          '.' +
          addLeadingZero(colorPrimaries) +
          '.' +
          addLeadingZero(transferCharacteristics) +
          '.' +
          addLeadingZero(matrixCoefficients) +
          '.' +
          videoFullRangeFlag;
        supplemental = parseSupplementalDoViCodec('dav1', sampleEntriesEnd);
      }
      break;
    }
    case 'ac-3':
    case 'ec-3':
    case 'alac':
    case 'fLaC':
    case 'Opus':
    default:
      break;
  }
  return { codec, encrypted, supplemental };
}

function parseSupplementalDoViCodec(
  fourCC: string,
  sampleEntriesEnd: Uint8Array,
): string | undefined {
  const dvvCResult = findBox(sampleEntriesEnd, ['dvvC']); // used by DoVi Profile 8 to 10
  const dvXCBox = dvvCResult.length
    ? dvvCResult[0]
    : findBox(sampleEntriesEnd, ['dvcC'])[0]; // used by DoVi Profiles up to 7 and 20
  if (dvXCBox as any) {
    const doViProfile = (dvXCBox[2] >> 1) & 0x7f;
    const doViLevel = ((dvXCBox[2] << 5) & 0x20) | ((dvXCBox[3] >> 3) & 0x1f);
    return (
      fourCC +
      '.' +
      addLeadingZero(doViProfile) +
      '.' +
      addLeadingZero(doViLevel)
    );
  }
}

function reverse32BitInt(val: number) {
  let result = 0;
  for (let i = 0; i < 32; i++) {
    result |= ((val >> i) & 1) << (32 - 1 - i);
  }
  return result >>> 0;
}

function skipBERInteger(bytes: Uint8Array, i: number): number {
  const limit = i + 5;
  while (bytes[i++] & 0x80 && i < limit) {
    /* do nothing */
  }
  return i;
}

function toHex(x: number): string {
  return ('0' + x.toString(16).toUpperCase()).slice(-2);
}

function addLeadingZero(num: number): string {
  return (num < 10 ? '0' : '') + num;
}

export function patchEncyptionData(
  initSegment: Uint8Array<ArrayBuffer> | undefined,
  decryptdata: DecryptData | null,
) {
  if (!initSegment || !decryptdata) {
    return;
  }
  const keyId = decryptdata.keyId;
  // FairPlay skd keys carry the key URI bytes as their keyId — only a 16 byte
  // key id can be written into the tenc default_KID field
  if (keyId?.byteLength === 16 && decryptdata.isCommonEncryption) {
    applyToTencBoxes(initSegment, (tenc, isAudio) => {
      // Look for default key id (keyID offset is always 8 within the tenc box):
      const tencKeyId = tenc.subarray(8, 24);
      if (!tencKeyId.some((b) => b !== 0)) {
        logger.log(
          `[eme] Patching keyId in 'enc${
            isAudio ? 'a' : 'v'
          }>sinf>>tenc' box: ${arrayToHex(tencKeyId)} -> ${arrayToHex(keyId)}`,
        );
        tenc.set(keyId, 8);
      }
    });
  }
}

export function parseKeyIdsFromTenc(
  initSegment: Uint8Array<ArrayBuffer>,
): Uint8Array<ArrayBuffer>[] {
  const keyIds: Uint8Array<ArrayBuffer>[] = [];
  applyToTencBoxes(initSegment, (tenc) => keyIds.push(tenc.subarray(8, 24)));
  return keyIds;
}

function applyToTencBoxes(
  initSegment: Uint8Array<ArrayBuffer>,
  predicate: (tenc: Uint8Array<ArrayBuffer>, isAudio: boolean) => void,
) {
  const traks = findBox(initSegment, ['moov', 'trak']);
  traks.forEach((trak) => {
    const stsd = findBox(trak, [
      'mdia',
      'minf',
      'stbl',
      'stsd',
    ])[0] as BoxDataOrUndefined;
    if (!stsd) return;
    const sampleEntries = stsd.subarray(8);
    let encBoxes = findBox(sampleEntries, ['enca']);
    const isAudio = encBoxes.length > 0;
    if (!isAudio) {
      encBoxes = findBox(sampleEntries, ['encv']);
    }
    encBoxes.forEach((enc) => {
      const encBoxChildren = isAudio ? enc.subarray(28) : enc.subarray(78);
      const sinfBoxes = findBox(encBoxChildren, ['sinf']);
      sinfBoxes.forEach((sinf) => {
        const tenc = parseSinf(sinf);
        if (tenc) {
          predicate(tenc, isAudio);
        }
      });
    });
  });
}

export function parseSinf(sinf: Uint8Array): BoxDataOrUndefined {
  const schm = findBox(sinf, ['schm'])[0] as BoxDataOrUndefined;
  if (schm) {
    const scheme = bin2str(schm.subarray(4, 8));
    if (scheme === 'cbcs' || scheme === 'cenc') {
      const tenc = findBox(sinf, ['schi', 'tenc'])[0] as BoxDataOrUndefined;
      if (tenc) {
        return tenc;
      }
    } else if (scheme === 'cbc2') {
      /* no-op */
    }
  }
}

/*
  For Reference:
  aligned(8) class TrackFragmentHeaderBox
           extends FullBox(‘tfhd’, 0, tf_flags){
     unsigned int(32)  track_ID;
     // all the following are optional fields
     unsigned int(64)  base_data_offset;
     unsigned int(32)  sample_description_index;
     unsigned int(32)  default_sample_duration;
     unsigned int(32)  default_sample_size;
     unsigned int(32)  default_sample_flags
  }
 */

type TrackFragmentRunSample = {
  cts?: number;
  duration: number;
  size: number;
  flags?: {
    dependsOn: 1 | 2;
    isNonSync: 0 | 1;
  };
};
type TrackFragmentRun = {
  sampleOffset: number;
  samples: TrackFragmentRunSample[];
  lastSampleDurationOffset?: number;
  defaultSampleDurationOffset?: number;
};
export type TrackTimes = {
  duration: number;
  keyFrameIndex?: number;
  keyFrameStart?: number;
  ptsMin?: number;
  ptsMax?: number;
  start: number;
  sampleCount: number;
  trun: TrackFragmentRun[];
  timescale: number;
  type: HdlrType;
};

export type ParsedSampleData = {
  includeSampleDetails: boolean;
  tracks: Record<number, TrackTimes>;
};

type SeiSampleContext = {
  isHEVCFlavor: boolean;
  samples: UserdataSample[];
  timeOffset: number;
  timescale: number;
  trackId: number;
};

type TrafBoxes = {
  moofOffset: number;
  tfdt: Uint8Array | undefined;
  tfhd: Uint8Array;
  truns: Uint8Array[];
};

let utf8TextDecoder: TextDecoder | undefined;

function decodeUtf8UserData(data: Uint8Array): string {
  if (typeof TextDecoder === 'undefined') {
    return utf8ArrayToStr(data);
  }
  const result = (utf8TextDecoder ||= new TextDecoder('utf-8')).decode(data);
  return result.replace(/\0/g, '');
}

function findMoofTrafs(data: Uint8Array): TrafBoxes[] {
  const end = data.byteLength;
  const trafs: TrafBoxes[] = [];

  for (let i = 0; i < end; ) {
    const hasHeader = i + 8 <= end;
    const size =
      i + 4 <= end
        ? data[i] * 0x1000000 +
          ((data[i + 1] << 16) | (data[i + 2] << 8) | data[i + 3])
        : readUint32(data, i);
    const endbox = size > 1 ? i + size : end;
    if (
      hasHeader &&
      data[i + 4] === 0x6d &&
      data[i + 5] === 0x6f &&
      data[i + 6] === 0x6f &&
      data[i + 7] === 0x66
    ) {
      const moofEnd = Math.min(endbox, end);
      for (let j = i + 8; j < moofEnd; ) {
        const childHasHeader = j + 8 <= moofEnd;
        const childSize =
          j + 4 <= moofEnd
            ? data[j] * 0x1000000 +
              ((data[j + 1] << 16) | (data[j + 2] << 8) | data[j + 3])
            : readUint32(data, j);
        const childEndbox = childSize > 1 ? j + childSize : moofEnd;
        if (
          childHasHeader &&
          data[j + 4] === 0x74 &&
          data[j + 5] === 0x72 &&
          data[j + 6] === 0x61 &&
          data[j + 7] === 0x66
        ) {
          const trafEnd = Math.min(childEndbox, moofEnd);
          let tfdt: Uint8Array | undefined;
          let tfhd: Uint8Array | undefined;
          const truns: Uint8Array[] = [];

          for (let k = j + 8; k < trafEnd; ) {
            const boxHasHeader = k + 8 <= trafEnd;
            const boxSize =
              k + 4 <= trafEnd
                ? data[k] * 0x1000000 +
                  ((data[k + 1] << 16) | (data[k + 2] << 8) | data[k + 3])
                : readUint32(data, k);
            const boxEnd = boxSize > 1 ? k + boxSize : trafEnd;

            if (boxHasHeader && data[k + 4] === 0x74) {
              const payloadEnd = Math.min(boxEnd, trafEnd);
              if (
                data[k + 5] === 0x66 &&
                data[k + 6] === 0x68 &&
                data[k + 7] === 0x64
              ) {
                tfhd ||= data.subarray(k + 8, payloadEnd);
              } else if (
                data[k + 5] === 0x66 &&
                data[k + 6] === 0x64 &&
                data[k + 7] === 0x74
              ) {
                tfdt ||= data.subarray(k + 8, payloadEnd);
              } else if (
                data[k + 5] === 0x72 &&
                data[k + 6] === 0x75 &&
                data[k + 7] === 0x6e
              ) {
                truns.push(data.subarray(k + 8, payloadEnd));
              }
            }
            k = boxEnd;
          }
          trafs.push({
            moofOffset: data.byteOffset + i,
            tfdt,
            tfhd: tfhd!,
            truns,
          });
        }
        j = childEndbox;
      }
    }
    i = endbox;
  }

  return trafs;
}

export function getSampleData(
  data: Uint8Array,
  initData: InitData,
  chunkMeta: ChunkMetadata,
  logger: ILogger,
  includeSampleDetails = true,
): Record<number, TrackTimes> {
  return parseSampleData(data, initData, logger, includeSampleDetails);
}

export function parseSamplesAndTiming(
  timeOffset: number,
  track: PassthroughTrack,
  initData: InitData,
  logger: ILogger,
  includeSampleDetails = false,
): {
  samples: UserdataSample[];
  sampleData: ParsedSampleData;
} {
  const samples: UserdataSample[] = [];
  const data = track.samples;
  const tracks = parseSampleData(data, initData, logger, includeSampleDetails, {
    isHEVCFlavor: isHEVC(track.codec),
    samples,
    timeOffset,
    timescale: track.timescale,
    trackId: track.id,
  });
  return {
    samples,
    sampleData: {
      includeSampleDetails,
      tracks,
    },
  };
}

function parseSampleData(
  data: Uint8Array,
  initData: InitData,
  logger: ILogger,
  includeSampleDetails: boolean,
  seiContext?: SeiSampleContext,
): Record<number, TrackTimes> {
  const tracks: Record<number, TrackTimes> = {};
  let hasTrackDuration = false;
  const trafs = findMoofTrafs(data);
  const eof = data.byteLength;
  for (let i = 0; i < trafs.length; i++) {
    const { moofOffset, tfdt, tfhd, truns } = trafs[i];
    // There is only one tfhd & trun per traf
    // This is true for CMAF style content, and we should perhaps check the ftyp
    // and only look for a single trun then, but for ISOBMFF we should check
    // for multiple track runs.
    // get the track id from the tfhd
    const id = readUint32(tfhd, 4);
    const track = initData[id];
    if (!track) {
      continue;
    }
    const trackTimes = (tracks[id] ||= {
      start: NaN,
      duration: 0,
      sampleCount: 0,
      trun: [],
      timescale: track.timescale,
      type: track.type,
    });
    // get start DTS
    let baseTime: number | undefined;

    if (tfdt) {
      const version = tfdt[0];
      baseTime = readUint32(tfdt, 4);
      if (version === 1) {
        // If value is too large, assume signed 64-bit. Negative track fragment decode times are invalid, but they exist in the wild.
        // This prevents large values from being used for initPTS, which can cause playlist sync issues.
        // https://github.com/video-dev/hls.js/issues/5303
        if (baseTime === UINT32_MAX) {
          logger.warn(
            `[mp4-demuxer]: Ignoring assumed invalid signed 64-bit track fragment decode time`,
          );
        } else {
          baseTime *= UINT32_MAX + 1;
          baseTime += readUint32(tfdt, 8);
        }
      }
      if (
        Number.isFinite(baseTime) &&
        (!Number.isFinite(trackTimes.start) || baseTime < trackTimes.start)
      ) {
        trackTimes.start = baseTime;
      }
      if (seiContext && Number.isFinite(baseTime)) {
        seiContext.timeOffset = baseTime! / seiContext.timescale;
      }
    }

    const scanSei =
      seiContext?.trackId === id && track.type === ElementaryStreamTypes.VIDEO;
    const trackDefault = track.default;
    const tfhdFlags = readUint32(tfhd, 0) & 0xffffff;
    // tfhd optional fields follow track_ID (at byte 8) in this fixed order,
    // each present only when its flag is set. Walk them so default_sample_size
    // is read at the correct offset regardless of which earlier fields exist.
    let defaultSampleDuration = trackDefault?.duration || 0;
    let defaultSampleDurationOffset: number | undefined;
    let defaultSampleSize = trackDefault?.sampleSize || 0;
    let tfhdOptOffset = 8;
    if (tfhdFlags & 0x000001) {
      // base_data_offset (64-bit)
      tfhdOptOffset += 8;
    }
    if (tfhdFlags & 0x000002) {
      // sample_description_index
      tfhdOptOffset += 4;
    }
    if (tfhdFlags & 0x000008) {
      // default_sample_duration
      defaultSampleDuration = readUint32(tfhd, tfhdOptOffset);
      defaultSampleDurationOffset =
        tfhd.byteOffset - data.byteOffset + tfhdOptOffset;
      tfhdOptOffset += 4;
    }
    if (tfhdFlags & 0x000010) {
      // default_sample_size
      defaultSampleSize = readUint32(tfhd, tfhdOptOffset);
    }
    let baseDataOffset = 0;
    const baseDataOffsetPresent = (tfhdFlags & 0x000001) !== 0;
    const defaultBaseIsMoof =
      !baseDataOffsetPresent && (tfhdFlags & 0x020000) !== 0;
    if (baseDataOffsetPresent) {
      // Should be 64 bit as per 14496-12 standard.
      // check for possible overflow, and log for now.
      baseDataOffset = readUint32(tfhd, 8);
      baseDataOffset *= Math.pow(2, 32);
      baseDataOffset += readUint32(tfhd, 12);
    } else if (defaultBaseIsMoof) {
      baseDataOffset = moofOffset;
    }

    let sampleDTS = baseTime || 0;
    let rawDuration = 0;
    let sampleDuration = defaultSampleDuration;
    for (let j = 0; j < truns.length; j++) {
      const trun = truns[j];
      // const version = trun[0];
      const sampleCount = readUint32(trun, 4);
      const sampleIndex = trackTimes.sampleCount;
      trackTimes.sampleCount += sampleCount;
      // Get duration from samples
      const dataOffsetPresent = trun[3] & 0x01;
      let dataOffset = 0;
      const firstSampleFlagsPresent = trun[3] & 0x04;
      const sampleDurationPresent = trun[2] & 0x01;
      const sampleSizePresent = trun[2] & 0x02;
      const sampleFlagsPresent = trun[2] & 0x04;
      const sampleCompositionTimeOffsetPresent = trun[2] & 0x08;
      let offset = 8;
      if (dataOffsetPresent) {
        dataOffset = readSint32(trun, offset);
        offset += 4;
      }
      if (firstSampleFlagsPresent) {
        const isNonSyncSample = trun[offset + 1] & 0x01;
        if (!isNonSyncSample && trackTimes.keyFrameIndex === undefined) {
          trackTimes.keyFrameIndex = sampleIndex;
        }
        offset += 4;
      }
      let sampleOffset = baseDataOffset + dataOffset;
      if (
        !includeSampleDetails &&
        trun[1] === 0 &&
        trun[2] === 0x06 &&
        trun[3] === 0x01
      ) {
        const runStartDTS = sampleDTS;
        const runStartOffset = sampleOffset;
        const trunSamplesOffset = offset;
        let firstSyncSample = -1;
        let firstSyncSampleEnd = 0;
        let fittingSampleCount = 0;
        let seiTimeOffset = seiContext?.timeOffset ?? 0;
        const seiSampleDuration =
          defaultSampleDuration / (seiContext?.timescale ?? 1);
        const hevcSei = seiContext?.isHEVCFlavor === true;
        const seiHeaderSize = hevcSei ? 2 : 1;

        for (let ix = 0; ix < sampleCount; ix++) {
          const size =
            trun[offset] === 0
              ? (trun[offset + 1] << 16) |
                (trun[offset + 2] << 8) |
                trun[offset + 3]
              : readUint32(trun, offset);
          const isFirstSyncSample =
            firstSyncSample === -1 &&
            trackTimes.keyFrameIndex === undefined &&
            (trun[offset + 5] & 0x01) === 0;
          offset += 8;
          const sampleEnd = sampleOffset + size;

          if (scanSei) {
            if (size > 0) {
              let naluOffset = sampleOffset;
              do {
                const naluSize =
                  data[naluOffset] === 0
                    ? (data[naluOffset + 1] << 16) |
                      (data[naluOffset + 2] << 8) |
                      data[naluOffset + 3]
                    : readUint32(data, naluOffset);
                naluOffset += 4;
                const naluHeader = data[naluOffset];
                const naluType = hevcSei
                  ? (naluHeader >> 1) & 0x3f
                  : naluHeader & 0x1f;
                const isSei = hevcSei
                  ? naluType === 39 || naluType === 40
                  : naluType === 6;
                if (isSei) {
                  parseSEIMessageFromNALu(
                    data.subarray(naluOffset, naluOffset + naluSize),
                    seiHeaderSize,
                    seiTimeOffset,
                    seiContext.samples,
                  );
                }
                naluOffset += naluSize;
              } while (naluOffset < sampleEnd);
            }
            seiTimeOffset += seiSampleDuration;
          }

          sampleOffset = sampleEnd;
          if (isFirstSyncSample) {
            firstSyncSample = ix;
            firstSyncSampleEnd = sampleOffset;
          }
        }

        if (sampleOffset <= eof) {
          fittingSampleCount = sampleCount;
        } else {
          let fittingOffset = runStartOffset;
          let fittingTrunOffset = trunSamplesOffset;
          for (let ix = 0; ix < sampleCount; ix++) {
            const size =
              trun[fittingTrunOffset] === 0
                ? (trun[fittingTrunOffset + 1] << 16) |
                  (trun[fittingTrunOffset + 2] << 8) |
                  trun[fittingTrunOffset + 3]
                : readUint32(trun, fittingTrunOffset);
            fittingOffset += size;
            if (fittingOffset > eof) {
              break;
            }
            fittingSampleCount = ix + 1;
            fittingTrunOffset += 8;
          }
        }
        if (scanSei) {
          seiContext.timeOffset = seiTimeOffset;
        }
        if (
          firstSyncSample !== -1 &&
          firstSyncSampleEnd <= eof &&
          trackTimes.keyFrameIndex === undefined
        ) {
          trackTimes.keyFrameIndex = firstSyncSample;
          trackTimes.keyFrameStart =
            runStartDTS + firstSyncSample * defaultSampleDuration;
        }
        if (fittingSampleCount) {
          if (
            !Number.isFinite(trackTimes.ptsMin) ||
            runStartDTS < trackTimes.ptsMin!
          ) {
            trackTimes.ptsMin = runStartDTS;
          }
          const lastSampleEnd =
            runStartDTS + fittingSampleCount * defaultSampleDuration;
          if (
            !Number.isFinite(trackTimes.ptsMax) ||
            lastSampleEnd > trackTimes.ptsMax!
          ) {
            trackTimes.ptsMax = lastSampleEnd;
          }
        }
        const runDuration = defaultSampleDuration * sampleCount;
        sampleDTS = runStartDTS + runDuration;
        rawDuration += runDuration;
        continue;
      }
      let samples: TrackFragmentRunSample[] | undefined;
      let fragRun: TrackFragmentRun | undefined;
      if (includeSampleDetails) {
        samples = [];
        fragRun = {
          sampleOffset,
          samples,
          defaultSampleDurationOffset,
        };
        if (sampleOffset <= eof) {
          trackTimes.trun.push(fragRun);
        }
      }
      let size;
      for (let ix = 0; ix < sampleCount; ix++) {
        let thisSampleDurationOffset: number | undefined;
        if (sampleDurationPresent) {
          if (includeSampleDetails) {
            thisSampleDurationOffset =
              trun.byteOffset - data.byteOffset + offset;
          }
          sampleDuration = readUint32(trun, offset);
          offset += 4;
        } else {
          sampleDuration = defaultSampleDuration;
        }
        if (sampleSizePresent) {
          size = readUint32(trun, offset);
          offset += 4;
        } else {
          size = defaultSampleSize;
        }
        let flags: TrackFragmentRunSample['flags'];
        let isNonSyncSample: 0 | 1 | undefined;
        if (sampleFlagsPresent) {
          isNonSyncSample = trun[offset + 1] & 0x01 ? 1 : 0;
          if (includeSampleDetails) {
            flags = {
              isNonSync: isNonSyncSample,
              dependsOn: (trun[offset] & 0x03) === 1 ? 1 : 2,
            };
          }
          offset += 4;
        }
        let cts = 0;
        if (sampleCompositionTimeOffsetPresent) {
          const version = trun[0];
          cts =
            version === 0 ? readUint32(trun, offset) : readSint32(trun, offset);
          offset += 4;
        }
        if (scanSei) {
          let naluOffset = sampleOffset;
          let naluTotalSize = 0;
          while (naluTotalSize < size) {
            const naluSize = readUint32(data, naluOffset);
            naluOffset += 4;
            if (isSEIMessage(seiContext.isHEVCFlavor, data[naluOffset])) {
              parseSEIMessageFromNALu(
                data.subarray(naluOffset, naluOffset + naluSize),
                seiContext.isHEVCFlavor ? 2 : 1,
                seiContext.timeOffset + cts / seiContext.timescale,
                seiContext.samples,
              );
            }
            naluOffset += naluSize;
            naluTotalSize += naluSize + 4;
          }
          seiContext.timeOffset += sampleDuration / seiContext.timescale;
        }
        sampleOffset += size;
        // Capture only fitting samples so a partial-mdat truncation
        // can still rewrite the right uint32 to balance EXTINF. Field
        // offsets above advance for every declared sample to stay aligned.
        if (sampleOffset <= eof) {
          if (fragRun && thisSampleDurationOffset !== undefined) {
            fragRun.lastSampleDurationOffset = thisSampleDurationOffset;
          }
          if (isNonSyncSample === 0 && trackTimes.keyFrameIndex === undefined) {
            trackTimes.keyFrameIndex = ix;
            trackTimes.keyFrameStart = sampleDTS;
          }
          const pts = sampleDTS + cts;
          if (!Number.isFinite(trackTimes.ptsMin) || pts < trackTimes.ptsMin!) {
            trackTimes.ptsMin = pts;
          }
          if (
            !Number.isFinite(trackTimes.ptsMax) ||
            pts + sampleDuration > trackTimes.ptsMax!
          ) {
            trackTimes.ptsMax = pts + sampleDuration;
          }
          if (samples) {
            samples[ix] = {
              cts,
              duration: sampleDuration,
              flags,
              size,
            };
          }
        }
        sampleDTS += sampleDuration;
        rawDuration += sampleDuration;
      }
      if (!rawDuration && defaultSampleDuration) {
        rawDuration += defaultSampleDuration * sampleCount;
      }
    }
    trackTimes.duration += rawDuration;
    if (trackTimes.duration) {
      hasTrackDuration = true;
    }
  }
  if (!hasTrackDuration) {
    // If duration samples are not available in the traf use sidx subsegment_duration
    let sidxMinStart = Infinity;
    let sidxMaxEnd = 0;
    const sidxs = findBox(data, ['sidx']);
    for (let i = 0; i < sidxs.length; i++) {
      const sidx = parseSegmentIndex(sidxs[i]);
      if (sidx?.references) {
        sidxMinStart = Math.min(
          sidxMinStart,
          sidx.earliestPresentationTime / sidx.timescale,
        );
        const subSegmentDuration = sidx.references.reduce(
          (dur, ref) => dur + ref.info.duration || 0,
          0,
        );
        sidxMaxEnd = Math.max(
          sidxMaxEnd,
          subSegmentDuration + sidx.earliestPresentationTime / sidx.timescale,
        );
      }
    }
    if (sidxMaxEnd && Number.isFinite(sidxMaxEnd)) {
      Object.keys(tracks).forEach((trackId) => {
        if (!tracks[trackId].duration) {
          tracks[trackId].duration =
            sidxMaxEnd * tracks[trackId].timescale - tracks[trackId].start;
        }
      });
    }
  }
  return tracks;
}

// TODO: Check if the last moof+mdat pair is part of the valid range
export function segmentValidRange(
  data: Uint8Array<ArrayBuffer>,
): SegmentedRange {
  const segmentedRange: SegmentedRange = {
    valid: null,
    remainder: null,
  };

  const moofs = findBox(data, ['moof']);
  if (moofs.length < 2) {
    segmentedRange.remainder = data;
    return segmentedRange;
  }
  const last = moofs[moofs.length - 1];
  // Offset by 8 bytes; findBox offsets the start by as much
  segmentedRange.valid = data.slice(0, last.byteOffset - 8);
  segmentedRange.remainder = data.slice(last.byteOffset - 8);
  return segmentedRange;
}

export interface SegmentedRange {
  valid: Uint8Array<ArrayBuffer> | null;
  remainder: Uint8Array<ArrayBuffer> | null;
}

export function appendUint8Array(data1: Uint8Array, data2: Uint8Array) {
  const temp = new Uint8Array(data1.length + data2.length);
  temp.set(data1);
  temp.set(data2, data1.length);
  return temp;
}

export interface IEmsgParsingData {
  schemeIdUri: string;
  value: string;
  timeScale: number;
  presentationTimeDelta?: number;
  presentationTime?: number;
  eventDuration: number;
  id: number;
  payload: Uint8Array;
}

export function parseSamples(
  timeOffset: number,
  track: PassthroughTrack,
): UserdataSample[] {
  const seiSamples = [] as UserdataSample[];
  const videoData = track.samples;
  const timescale = track.timescale;
  const trackId = track.id;
  let isHEVCFlavor = false;

  const moofs = findBox(videoData, ['moof']);
  moofs.map((moof) => {
    const moofOffset = moof.byteOffset - 8;
    const trafs = findBox(moof, ['traf']);
    trafs.map((traf) => {
      // get the base media decode time from the tfdt
      const baseTime = findBox(traf, ['tfdt']).map((tfdt) => {
        const version = tfdt[0];
        let result = readUint32(tfdt, 4);
        if (version === 1) {
          result *= Math.pow(2, 32);
          result += readUint32(tfdt, 8);
        }
        return result / timescale;
      })[0];

      if ((baseTime as any) !== undefined) {
        timeOffset = baseTime;
      }

      return findBox(traf, ['tfhd']).map((tfhd) => {
        const id = readUint32(tfhd, 4);
        const tfhdFlags = readUint32(tfhd, 0) & 0xffffff;
        const baseDataOffsetPresent = (tfhdFlags & 0x000001) !== 0;
        let baseDataOffset = 0;
        const sampleDescriptionIndexPresent = (tfhdFlags & 0x000002) !== 0;
        const defaultSampleDurationPresent = (tfhdFlags & 0x000008) !== 0;
        let defaultSampleDuration = 0;
        const defaultSampleSizePresent = (tfhdFlags & 0x000010) !== 0;
        let defaultSampleSize = 0;
        const defaultSampleFlagsPresent = (tfhdFlags & 0x000020) !== 0;
        const defaultBaseIsMoof =
          !baseDataOffsetPresent && (tfhdFlags & 0x020000) !== 0;
        let tfhdOffset = 8;

        if (id === trackId) {
          if (baseDataOffsetPresent) {
            baseDataOffset = readUint32(tfhd, tfhdOffset);
            tfhdOffset += 4;
            baseDataOffset *= Math.pow(2, 32);
            baseDataOffset += readUint32(tfhd, tfhdOffset);
            tfhdOffset += 4;
          } else if (defaultBaseIsMoof) {
            baseDataOffset = moofOffset;
          }
          if (sampleDescriptionIndexPresent) {
            tfhdOffset += 4;
          }
          if (defaultSampleDurationPresent) {
            defaultSampleDuration = readUint32(tfhd, tfhdOffset);
            tfhdOffset += 4;
          }
          if (defaultSampleSizePresent) {
            defaultSampleSize = readUint32(tfhd, tfhdOffset);
            tfhdOffset += 4;
          }
          if (defaultSampleFlagsPresent) {
            tfhdOffset += 4;
          }
          if (track.type === 'video') {
            isHEVCFlavor = isHEVC(track.codec);
          }

          findBox(traf, ['trun']).map((trun) => {
            const version = trun[0];
            const flags = readUint32(trun, 0) & 0xffffff;
            const dataOffsetPresent = (flags & 0x000001) !== 0;
            let dataOffset = 0;
            const firstSampleFlagsPresent = (flags & 0x000004) !== 0;
            const sampleDurationPresent = (flags & 0x000100) !== 0;
            let sampleDuration = 0;
            const sampleSizePresent = (flags & 0x000200) !== 0;
            let sampleSize = 0;
            const sampleFlagsPresent = (flags & 0x000400) !== 0;
            const sampleCompositionOffsetsPresent = (flags & 0x000800) !== 0;
            let compositionOffset = 0;
            const sampleCount = readUint32(trun, 4);
            let trunOffset = 8; // past version, flags, and sample count

            if (dataOffsetPresent) {
              dataOffset = readUint32(trun, trunOffset);
              trunOffset += 4;
            }
            if (firstSampleFlagsPresent) {
              trunOffset += 4;
            }
            let sampleOffset = baseDataOffset + dataOffset;
            for (let ix = 0; ix < sampleCount; ix++) {
              if (sampleDurationPresent) {
                sampleDuration = readUint32(trun, trunOffset);
                trunOffset += 4;
              } else {
                sampleDuration = defaultSampleDuration;
              }
              if (sampleSizePresent) {
                sampleSize = readUint32(trun, trunOffset);
                trunOffset += 4;
              } else {
                sampleSize = defaultSampleSize;
              }
              if (sampleFlagsPresent) {
                trunOffset += 4;
              }
              if (sampleCompositionOffsetsPresent) {
                if (version === 0) {
                  compositionOffset = readUint32(trun, trunOffset);
                } else {
                  compositionOffset = readSint32(trun, trunOffset);
                }
                trunOffset += 4;
              }
              if (track.type === ElementaryStreamTypes.VIDEO) {
                let naluTotalSize = 0;
                while (naluTotalSize < sampleSize) {
                  const naluSize = readUint32(videoData, sampleOffset);
                  sampleOffset += 4;
                  if (isSEIMessage(isHEVCFlavor, videoData[sampleOffset])) {
                    const data = videoData.subarray(
                      sampleOffset,
                      sampleOffset + naluSize,
                    );
                    parseSEIMessageFromNALu(
                      data,
                      isHEVCFlavor ? 2 : 1,
                      timeOffset + compositionOffset / timescale,
                      seiSamples,
                    );
                  }
                  sampleOffset += naluSize;
                  naluTotalSize += naluSize + 4;
                }
              }

              timeOffset += sampleDuration / timescale;
            }
          });
        }
      });
    });
  });
  return seiSamples;
}

export function isHEVC(codec: string | undefined) {
  if (!codec) {
    return false;
  }
  const baseCodec = codec.substring(0, 4);
  return (
    baseCodec === 'hvc1' ||
    baseCodec === 'hev1' ||
    // Dolby Vision
    baseCodec === 'dvh1' ||
    baseCodec === 'dvhe'
  );
}

function isSEIMessage(isHEVCFlavor: boolean, naluHeader: number) {
  if (isHEVCFlavor) {
    const naluType = (naluHeader >> 1) & 0x3f;
    return naluType === 39 || naluType === 40;
  } else {
    const naluType = naluHeader & 0x1f;
    return naluType === 6;
  }
}

export function parseSEIMessageFromNALu(
  unescapedData: Uint8Array,
  headerSize: number,
  pts: number,
  samples: UserdataSample[],
) {
  const data = discardEPB(unescapedData);
  let seiPtr = 0;
  // skip nal header
  seiPtr += headerSize;
  let payloadType = 0;
  let payloadSize = 0;
  let b = 0;

  while (seiPtr < data.length) {
    payloadType = 0;
    do {
      if (seiPtr >= data.length) {
        break;
      }
      b = data[seiPtr++];
      payloadType += b;
    } while (b === 0xff);

    // Parse payload size.
    payloadSize = 0;
    do {
      if (seiPtr >= data.length) {
        break;
      }
      b = data[seiPtr++];
      payloadSize += b;
    } while (b === 0xff);

    const leftOver = data.length - seiPtr;
    // Create a variable to process the payload
    let payPtr = seiPtr;

    // Increment the seiPtr to the end of the payload
    if (payloadSize < leftOver) {
      seiPtr += payloadSize;
    } else if (payloadSize > leftOver) {
      // Some type of corruption has happened?
      logger.error(
        `Malformed SEI payload. ${payloadSize} is too small, only ${leftOver} bytes left to parse.`,
      );
      // We might be able to parse some data, but let's be safe and ignore it.
      break;
    }

    if (payloadType === 4) {
      const countryCode = data[payPtr++];
      if (countryCode === 181) {
        const providerCode = readUint16(data, payPtr);
        payPtr += 2;

        if (providerCode === 49) {
          const userStructure = readUint32(data, payPtr);
          payPtr += 4;

          if (userStructure === 0x47413934) {
            const userDataType = data[payPtr++];

            // Raw CEA-608 bytes wrapped in CEA-708 packet
            if (userDataType === 3) {
              const firstByte = data[payPtr++];
              const totalCCs = 0x1f & firstByte;
              const enabled = 0x40 & firstByte;
              const totalBytes = enabled ? 2 + totalCCs * 3 : 0;
              const byteArray = new Uint8Array(totalBytes);
              if (enabled) {
                byteArray[0] = firstByte;
                for (let i = 1; i < totalBytes; i++) {
                  byteArray[i] = data[payPtr++];
                }
              }

              samples.push({
                type: userDataType,
                payloadType,
                pts,
                bytes: byteArray,
              });
            }
          }
        }
      }
    } else if (payloadType === 5) {
      if (payloadSize > 16) {
        const uuidStrArray: Array<string> = [];
        for (let i = 0; i < 16; i++) {
          const b = data[payPtr++].toString(16);
          uuidStrArray.push(b.length == 1 ? '0' + b : b);

          if (i === 3 || i === 5 || i === 7 || i === 9) {
            uuidStrArray.push('-');
          }
        }
        const length = payloadSize - 16;
        const userDataBytes = new Uint8Array(length);
        for (let i = 0; i < length; i++) {
          userDataBytes[i] = data[payPtr++];
        }

        samples.push({
          payloadType,
          pts,
          uuid: uuidStrArray.join(''),
          userData: decodeUtf8UserData(userDataBytes),
          userDataBytes,
        });
      }
    }
  }
}

/**
 * remove Emulation Prevention bytes from a RBSP
 */
export function discardEPB(data: Uint8Array): Uint8Array {
  const length = data.byteLength;
  let epbPositions: number[] | undefined;
  let position = data.indexOf(0x03, 3);

  // Find all `Emulation Prevention Bytes`
  while (position !== -1) {
    if (data[position - 1] === 0 && data[position - 2] === 0) {
      (epbPositions ||= []).push(position);
    }
    position = data.indexOf(0x03, position + 1);
  }

  // If no Emulation Prevention Bytes were found just return the original
  // array
  if (!epbPositions) {
    return data;
  }

  // Create a new array to hold the NAL unit data
  const newLength = length - epbPositions.length;
  const newData = new Uint8Array(newLength);
  let epbIndex = 0;
  let sourceIndex = 0;

  for (let i = 0; i < newLength; sourceIndex++, i++) {
    if (sourceIndex === epbPositions[epbIndex]) {
      // Skip this byte
      sourceIndex++;
      epbIndex++;
    }
    newData[i] = data[sourceIndex];
  }
  return newData;
}

export function parseEmsg(data: Uint8Array): IEmsgParsingData {
  const version = data[0];
  let schemeIdUri: string = '';
  let value: string = '';
  let timeScale: number = 0;
  let presentationTimeDelta: number = 0;
  let presentationTime: number | undefined;
  let eventDuration: number = 0;
  let id: number = 0;
  // Skip the FullBox version and flags
  let offset: number = 4;

  if (version === 0) {
    const scheme = readCString(data, offset);
    const schemeValue =
      scheme !== null ? readCString(data, offset + scheme.length) : null;

    if (scheme !== null && schemeValue !== null) {
      schemeIdUri = scheme;
      value = schemeValue;
      offset += scheme.length + schemeValue.length;

      timeScale = readUint32(data, offset);
      offset += 4;
      presentationTimeDelta = readUint32(data, offset);
      offset += 4;
      eventDuration = readUint32(data, offset);
      offset += 4;
      id = readUint32(data, offset);
      offset += 4;
    } else {
      logger.warn(
        `Unterminated ${scheme === null ? 'scheme_id_uri' : 'value'} in parsing emsg box: version 0 box ends inside a string, dropping all of its fields`,
      );
      // The box ends inside a string, so every field of the box follows it
      offset = data.length;
    }
  } else if (version === 1) {
    timeScale = readUint32(data, offset);
    offset += 4;
    const leftPresentationTime = readUint32(data, offset);
    offset += 4;
    const rightPresentationTime = readUint32(data, offset);
    offset += 4;
    presentationTime = 2 ** 32 * leftPresentationTime + rightPresentationTime;
    if (!Number.isSafeInteger(presentationTime)) {
      presentationTime = Number.MAX_SAFE_INTEGER;
      logger.warn(
        'Presentation time exceeds safe integer limit and wrapped to max safe integer in parsing emsg box',
      );
    }

    eventDuration = readUint32(data, offset);
    offset += 4;
    id = readUint32(data, offset);
    offset += 4;

    const scheme = readCString(data, offset);
    const schemeValue =
      scheme !== null ? readCString(data, offset + scheme.length) : null;

    if (scheme !== null) {
      schemeIdUri = scheme;
      offset += scheme.length;
    }
    if (schemeValue !== null) {
      value = schemeValue;
      offset += schemeValue.length;
    } else {
      logger.warn(
        `Unterminated ${scheme === null ? 'scheme_id_uri' : 'value'} in parsing emsg box: version 1 box ends inside a string, dropping its ${scheme === null ? 'strings and payload' : 'value and payload'}`,
      );
      // The box ends inside a string, so it carries no payload
      offset = data.length;
    }
  }
  const payload = data.subarray(offset, data.byteLength);

  return {
    schemeIdUri,
    value,
    timeScale,
    presentationTime,
    presentationTimeDelta,
    eventDuration,
    id,
    payload,
  };
}

export function mp4Box(type: ArrayLike<number>, ...payload: Uint8Array[]) {
  const len = payload.length;
  let size = 8;
  let i = len;
  while (i--) {
    size += payload[i].byteLength;
  }
  const result = new Uint8Array(size);
  result[0] = (size >> 24) & 0xff;
  result[1] = (size >> 16) & 0xff;
  result[2] = (size >> 8) & 0xff;
  result[3] = size & 0xff;
  result.set(type, 4);
  for (i = 0, size = 8; i < len; i++) {
    result.set(payload[i], size);
    size += payload[i].byteLength;
  }
  return result;
}

export function mp4pssh(
  systemId: Uint8Array,
  keyids: Array<Uint8Array> | null,
  data: Uint8Array,
) {
  if (systemId.byteLength !== 16) {
    throw new RangeError('Invalid system id');
  }
  let version;
  let kids;
  if (keyids) {
    version = 1;
    kids = new Uint8Array(keyids.length * 16);
    for (let ix = 0; ix < keyids.length; ix++) {
      const k = keyids[ix]; // uint8array
      if (k.byteLength !== 16) {
        throw new RangeError('Invalid key');
      }
      kids.set(k, ix * 16);
    }
  } else {
    version = 0;
    kids = new Uint8Array();
  }
  let kidCount;
  if (version > 0) {
    kidCount = new Uint8Array(4);
    if (keyids!.length > 0) {
      new DataView(kidCount.buffer).setUint32(0, keyids!.length, false);
    }
  } else {
    kidCount = new Uint8Array();
  }
  const dataSize = new Uint8Array(4);
  if (data.byteLength > 0) {
    new DataView(dataSize.buffer).setUint32(0, data.byteLength, false);
  }
  return mp4Box(
    [112, 115, 115, 104],
    new Uint8Array([
      version,
      0x00,
      0x00,
      0x00, // Flags
    ]),
    systemId, // 16 bytes
    kidCount,
    kids,
    dataSize,
    data,
  );
}

export type PsshData = {
  version: 0 | 1;
  systemId: KeySystemIds;
  kids: null | Uint8Array<ArrayBuffer>[];
  data: null | Uint8Array<ArrayBuffer>;
  offset: number;
  size: number;
};

export type PsshInvalidResult = {
  systemId?: undefined;
  kids?: undefined;
  offset: number;
  size: number;
};

export function parseMultiPssh(
  initData: ArrayBuffer,
): (PsshData | PsshInvalidResult)[] {
  const results: (PsshData | PsshInvalidResult)[] = [];
  if (initData instanceof ArrayBuffer) {
    const length = initData.byteLength;
    let offset = 0;
    while (offset + 32 < length) {
      const view = new DataView(initData, offset);
      const pssh = parsePssh(view);
      results.push(pssh);
      offset += pssh.size;
    }
  }
  return results;
}

function parseWidevinePsshKids(
  data: Uint8Array<ArrayBuffer>,
): Uint8Array<ArrayBuffer>[] {
  const kids: Uint8Array<ArrayBuffer>[] = [];
  for (let i = 0; i < data.length; ) {
    const tag = data[i++];
    const wireType = tag & 7;
    if (wireType === 0) {
      // Varint
      while (data[i++] & 0x80) {
        /* empty */
      }
      continue;
    }
    if (wireType !== 2) {
      // 1	64-bit fixed // 5	32-bit fixed
      i += wireType === 1 ? 8 : 4;
      continue;
    }
    let len = 0;
    for (let shift = 0, b = 0x80; b & 0x80; shift += 7) {
      len |= ((b = data[i++]) & 0x7f) << shift;
    }
    if (tag >> 3 === 2) {
      // key_id - 16 raw bytes or 32-byte ASCII hex string
      if (len === 32) {
        const kid = new Uint8Array(16) as Uint8Array<ArrayBuffer>;
        for (let j = 0; j < 16; j++) {
          kid[j] = parseInt(
            String.fromCharCode(data[i + j * 2], data[i + j * 2 + 1]),
            16,
          );
        }
        kids.push(kid);
      } else if (len === 16) {
        kids.push(data.subarray(i, i + 16));
      }
    }
    i += len;
  }
  return kids;
}

function parsePssh(view: DataView<ArrayBuffer>): PsshData | PsshInvalidResult {
  const size = view.getUint32(0);
  const offset = view.byteOffset;
  const length = view.byteLength;
  if (length < size) {
    return {
      offset,
      size: length,
    };
  }
  const type = view.getUint32(4);
  if (type !== 0x70737368) {
    return { offset, size };
  }
  const version = view.getUint32(8) >>> 24;
  if (version !== 0 && version !== 1) {
    return { offset, size };
  }
  const buffer = view.buffer;
  const systemId = arrayToHex(
    new Uint8Array(buffer, offset + 12, 16),
  ) as KeySystemIds;

  let kids: null | Uint8Array<ArrayBuffer>[] = null;
  let data: null | Uint8Array<ArrayBuffer> = null;
  let dataSizeOffset = 0;

  if (version === 0) {
    dataSizeOffset = 28;
  } else {
    const kidCounts = view.getUint32(28);
    if (!kidCounts || length < 32 + kidCounts * 16) {
      return { offset, size };
    }
    kids = [];
    for (let i = 0; i < kidCounts; i++) {
      kids.push(new Uint8Array(buffer, offset + 32 + i * 16, 16));
    }
    dataSizeOffset = 32 + kidCounts * 16;
  }

  if (!dataSizeOffset) {
    return { offset, size };
  }

  const dataSizeOrKidCount = view.getUint32(dataSizeOffset);
  if (size - 32 < dataSizeOrKidCount) {
    return { offset, size };
  }
  data = new Uint8Array(
    buffer,
    offset + dataSizeOffset + 4,
    dataSizeOrKidCount,
  );
  if (version === 0) {
    kids = parseWidevinePsshKids(data);
  }
  return {
    version,
    systemId,
    kids,
    data,
    offset,
    size,
  };
}
