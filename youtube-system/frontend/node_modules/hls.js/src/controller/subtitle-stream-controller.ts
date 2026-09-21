import BaseStreamController, { State } from './base-stream-controller';
import { FragmentState } from './fragment-tracker';
import { ErrorDetails, ErrorTypes } from '../errors';
import { Events } from '../events';
import {
  type Fragment,
  isMediaFragment,
  type MediaFragment,
  type Part,
} from '../loader/fragment';
import { Level } from '../types/level';
import { PlaylistLevelType } from '../types/loader';
import { BufferHelper } from '../utils/buffer-helper';
import { alignStream } from '../utils/discontinuities';
import {
  getAesModeFromFullSegmentMethod,
  isFullSegmentEncryption,
} from '../utils/encryption-methods-util';
import { subtitleOptionsIdentical } from '../utils/media-option-attributes';
import type { FragmentTracker } from './fragment-tracker';
import type Hls from '../hls';
import type KeyLoader from '../loader/key-loader';
import type { LevelDetails } from '../loader/level-details';
import type { NetworkComponentAPI } from '../types/component-api';
import type {
  BufferFlushingData,
  ErrorData,
  FragLoadedData,
  LevelLoadedData,
  MediaDetachingData,
  SubtitleFragProcessed,
  SubtitleTracksUpdatedData,
  TrackLoadedData,
  TrackSwitchedData,
} from '../types/events';
import type { Bufferable } from '../utils/buffer-helper';

const TICK_INTERVAL = 500; // how often to tick in ms

interface TimeRange {
  start: number;
  end: number;
}

export class SubtitleStreamController
  extends BaseStreamController
  implements NetworkComponentAPI
{
  private currentTrackId: number = -1;
  private tracksBuffered: Array<TimeRange[] | undefined> = [];
  private mainDetails: LevelDetails | null = null;

  constructor(
    hls: Hls,
    fragmentTracker: FragmentTracker,
    keyLoader: KeyLoader,
  ) {
    super(
      hls,
      fragmentTracker,
      keyLoader,
      'subtitle-stream-controller',
      PlaylistLevelType.SUBTITLE,
    );
    this.registerListeners();
  }

  protected onHandlerDestroying() {
    this.unregisterListeners();
    super.onHandlerDestroying();
    this.mainDetails = null;
  }

  protected registerListeners() {
    super.registerListeners();
    const { hls } = this;
    hls.on(Events.LEVEL_LOADED, this.onLevelLoaded, this);
    hls.on(Events.SUBTITLE_TRACKS_UPDATED, this.onSubtitleTracksUpdated, this);
    hls.on(Events.SUBTITLE_TRACK_SWITCH, this.onSubtitleTrackSwitch, this);
    hls.on(Events.SUBTITLE_TRACK_LOADED, this.onSubtitleTrackLoaded, this);
    hls.on(Events.SUBTITLE_FRAG_PROCESSED, this.onSubtitleFragProcessed, this);
    hls.on(Events.BUFFER_FLUSHING, this.onBufferFlushing, this);
  }

  protected unregisterListeners() {
    super.unregisterListeners();
    const { hls } = this;
    hls.off(Events.LEVEL_LOADED, this.onLevelLoaded, this);
    hls.off(Events.SUBTITLE_TRACKS_UPDATED, this.onSubtitleTracksUpdated, this);
    hls.off(Events.SUBTITLE_TRACK_SWITCH, this.onSubtitleTrackSwitch, this);
    hls.off(Events.SUBTITLE_TRACK_LOADED, this.onSubtitleTrackLoaded, this);
    hls.off(Events.SUBTITLE_FRAG_PROCESSED, this.onSubtitleFragProcessed, this);
    hls.off(Events.BUFFER_FLUSHING, this.onBufferFlushing, this);
  }

  startLoad(startPosition: number, skipSeekToStartPosition?: boolean) {
    this.stopLoad();
    this.state = State.IDLE;

    this.setInterval(TICK_INTERVAL);

    this.nextLoadPosition = this.lastCurrentTime =
      startPosition + this.timelineOffset;
    this.startPosition = skipSeekToStartPosition ? -1 : startPosition;

    this.tick();
  }

  protected onManifestLoading() {
    super.onManifestLoading();
    this.mainDetails = null;
  }

  protected onMediaDetaching(
    event: Events.MEDIA_DETACHING,
    data: MediaDetachingData,
  ) {
    this.tracksBuffered = [];
    super.onMediaDetaching(event, data);
  }

  private onLevelLoaded(event: Events.LEVEL_LOADED, data: LevelLoadedData) {
    this.mainDetails = data.details;
  }

  private onSubtitleFragProcessed(
    event: Events.SUBTITLE_FRAG_PROCESSED,
    data: SubtitleFragProcessed,
  ) {
    const { frag, part, success } = data;
    if (!success) {
      return;
    }

    const buffered = this.tracksBuffered[this.currentTrackId];
    if (!buffered) {
      return;
    }

    // Create/update a buffered array matching the interface used by BufferHelper.bufferedInfo
    // so we can re-use the logic used to detect how much has been buffered
    let timeRange: TimeRange | undefined;
    const start = (part || frag).start;
    for (let i = 0; i < buffered.length; i++) {
      if (start >= buffered[i].start && start <= buffered[i].end) {
        timeRange = buffered[i];
        break;
      }
    }

    const end = start + (part || frag).duration;
    if (timeRange) {
      timeRange.end = end;
    } else {
      timeRange = { start, end };
      buffered.push(timeRange);
    }
    if (!part || end >= frag.end) {
      const entity = this.fragmentTracker.fragBuffered(frag as MediaFragment);
      if (part && entity) {
        entity.range.subs = {
          time: [{ startPTS: frag.start, endPTS: end }],
          partial: true,
        };
      }
      if (isMediaFragment(frag) && !this.fragContextChanged(frag)) {
        this.fragPrevious = frag;
      }
      this.fragBufferedComplete(frag, part);
      if (this.media) {
        this.tickImmediate();
      }
    }
  }

  private onBufferFlushing(
    event: Events.BUFFER_FLUSHING,
    data: BufferFlushingData,
  ) {
    const { startOffset, endOffset } = data;
    if (startOffset === 0 && endOffset !== Number.POSITIVE_INFINITY) {
      const endOffsetSubtitles = endOffset - 1;
      if (endOffsetSubtitles <= 0) {
        return;
      }
      data.endOffsetSubtitles = Math.max(0, endOffsetSubtitles);
      this.tracksBuffered.forEach((buffered) => {
        if (!buffered) return;
        for (let i = 0; i < buffered.length; ) {
          if (buffered[i].end <= endOffsetSubtitles) {
            buffered.shift();
            continue;
          } else if (buffered[i].start < endOffsetSubtitles) {
            buffered[i].start = endOffsetSubtitles;
          } else {
            break;
          }
          i++;
        }
      });
      this.fragmentTracker.removeFragmentsInRange(
        startOffset,
        endOffsetSubtitles,
        PlaylistLevelType.SUBTITLE,
      );
    }
  }

  // If something goes wrong, proceed to next frag, if we were processing one.
  protected onError(event: Events.ERROR, data: ErrorData) {
    const frag = data.frag;

    if (frag?.type === PlaylistLevelType.SUBTITLE) {
      if (data.details === ErrorDetails.FRAG_GAP) {
        this.fragmentTracker.addAsGap(frag as MediaFragment);
      }
      if (this.fragCurrent) {
        this.fragCurrent.abortRequests();
      }
      if (this.state !== State.STOPPED) {
        this.state = State.IDLE;
      }
    }
  }

  // Got all new subtitle levels.
  private onSubtitleTracksUpdated(
    event: Events.SUBTITLE_TRACKS_UPDATED,
    { subtitleTracks }: SubtitleTracksUpdatedData,
  ) {
    if (this.levels && subtitleOptionsIdentical(this.levels, subtitleTracks)) {
      this.levels = subtitleTracks.map(
        (mediaPlaylist) => new Level(mediaPlaylist),
      );
      return;
    }
    this.tracksBuffered = [];
    this.levels = subtitleTracks.map((mediaPlaylist) => {
      const level = new Level(mediaPlaylist);
      this.tracksBuffered[level.id] = [];
      return level;
    });
    this.fragmentTracker.removeFragmentsInRange(
      0,
      Number.POSITIVE_INFINITY,
      PlaylistLevelType.SUBTITLE,
    );
    this.fragPrevious = null;
    this.mediaBuffer = null;
  }

  private onSubtitleTrackSwitch(
    event: Events.SUBTITLE_TRACK_SWITCH,
    data: TrackSwitchedData,
  ) {
    this.currentTrackId = data.id;

    this.abortCurrentFrag();
    if (!this.levels?.length || this.currentTrackId === -1) {
      this.clearInterval();
      return;
    }

    // Check if track has the necessary details to load fragments
    const currentTrack = this.levels[this.currentTrackId] as Level | undefined;
    if (!currentTrack?.details) {
      this.mediaBuffer = null;
      return;
    }
    this.mediaBuffer = this.mediaBufferTimeRanges;
    if (this.state !== State.STOPPED) {
      this.setInterval(TICK_INTERVAL);
    }
  }

  // Got a new set of subtitle fragments.
  private onSubtitleTrackLoaded(
    event: Events.SUBTITLE_TRACK_LOADED,
    data: TrackLoadedData,
  ) {
    const { currentTrackId, levels } = this;
    const { details: newDetails, id: trackId } = data;
    if (!levels) {
      this.warn(`Subtitle tracks were reset while loading level ${trackId}`);
      return;
    }
    const track = levels[trackId] as Level | undefined;
    if (trackId >= levels.length || !track) {
      return;
    }
    this.log(
      `Subtitle track ${trackId} loaded [${newDetails.startSN},${
        newDetails.endSN
      }]${
        newDetails.lastPartSn
          ? `[part-${newDetails.lastPartSn}-${newDetails.lastPartIndex}]`
          : ''
      },duration:${newDetails.totalduration}`,
    );
    this.mediaBuffer = this.mediaBufferTimeRanges;

    const mainDetails = this.mainDetails;
    let sliding = 0;
    if (newDetails.live || track.details?.live) {
      if (newDetails.deltaUpdateFailed) {
        return;
      }
      if (!mainDetails) {
        this.startFragRequested = false;
        return;
      }
      if (track.details) {
        sliding = this.alignPlaylists(
          newDetails,
          track.details,
          this.levelLastLoaded?.details,
        );
      }
      if (!newDetails.alignedSliding) {
        // line up live playlist with main so that fragments in range are loaded
        alignStream(mainDetails, newDetails, this);
        sliding = newDetails.fragmentStart;
      }
    }

    track.details = newDetails;
    this.levelLastLoaded = track;

    // compute start position if we are aligned with the main playlist
    if (mainDetails && !this.startFragRequested) {
      this.setStartPosition(mainDetails, sliding);
    }

    if (trackId !== currentTrackId) {
      return;
    }

    this.hls.trigger(Events.SUBTITLE_TRACK_UPDATED, {
      details: newDetails,
      id: trackId,
      groupId: data.groupId,
    });

    // trigger handler right now
    this.tickImmediate();
  }

  // Decrypt encrypted VTT parts as they arrive. The base class leaves progress a
  // no-op for subtitles, so without this override encrypted parts would only decrypt
  // at full-segment boundaries, losing the low-latency path.
  protected _handleFragmentLoadProgress(data: FragLoadedData) {
    const { frag, part, payload } = data;
    if (!part || !payload?.byteLength || !this.shouldDecrypt(frag)) {
      return;
    }
    this.decryptPayload(payload, frag, part);
  }

  _handleFragmentLoadComplete(fragLoadedData: FragLoadedData) {
    const { frag, payload } = fragLoadedData;
    if (
      this.fragContextChanged(frag) ||
      !payload?.byteLength ||
      !this.shouldDecrypt(frag)
    ) {
      return;
    }
    this.decryptPayload(payload, frag, null);
  }

  private shouldDecrypt(frag: Fragment): boolean {
    const d = frag.decryptdata;
    return !!(d?.key && d.iv && isFullSegmentEncryption(d.method));
  }

  // Decrypt a full segment (part === null) or a single LL-HLS part and emit
  // FRAG_DECRYPTED. On full-segment failure, reset to IDLE so the next tick retries.
  private decryptPayload(
    payload: ArrayBuffer,
    frag: Fragment,
    part: Part | null,
  ): void {
    const decryptData = frag.decryptdata!;
    const tstart = performance.now();
    this.decrypter
      .decrypt(
        new Uint8Array(payload),
        decryptData.key!.buffer,
        decryptData.iv!.buffer,
        getAesModeFromFullSegmentMethod(decryptData.method),
      )
      .then((plaintext) => {
        if (this.fragContextChanged(frag)) {
          return;
        }
        this.hls.trigger(Events.FRAG_DECRYPTED, {
          frag,
          part,
          payload: plaintext,
          stats: { tstart, tdecrypt: performance.now() },
        });
      })
      .catch((err) => {
        this.hls.trigger(Events.ERROR, {
          type: ErrorTypes.MEDIA_ERROR,
          details: ErrorDetails.FRAG_DECRYPT_ERROR,
          fatal: false,
          error: err,
          reason: err.message,
          frag,
          part,
        });
        if (!part) {
          this.warn(`${err.name}: ${err.message}`);
          this.state = State.IDLE;
        }
      });
  }

  doTick() {
    if (this.state === State.IDLE && this.levels) {
      if (
        !this.media &&
        !this.primaryPrefetch &&
        (this.startFragRequested || !this.config.startFragPrefetch)
      ) {
        return;
      }
      const { currentTrackId, levels } = this;
      const track = levels[currentTrackId];
      const trackDetails = track?.details;
      if (
        !trackDetails ||
        this.waitForLive(track) ||
        this.waitForCdnTuneIn(trackDetails)
      ) {
        this.startFragRequested = false;
        return;
      }
      const { config } = this;
      const currentTime = this.playhead;
      const bufferedInfo = BufferHelper.bufferedInfo(
        this.tracksBuffered[this.currentTrackId] || [],
        currentTime,
        config.maxBufferHole,
      );
      const { end: targetBufferTime, len: bufferLen } = bufferedInfo;
      const maxBufLen = Math.max(
        this.hls.maxBufferLength + trackDetails.levelTargetDuration,
        this.hls.mainForwardBufferInfo?.len || 0,
      );

      if (bufferLen > maxBufLen || (bufferLen && !this.buffering)) {
        return;
      }
      let frag = this.getNextFragment(targetBufferTime, trackDetails);
      if (!frag) {
        return;
      }
      // Load earlier fragment in same discontinuity to make up for misaligned playlists and cues that extend beyond end of segment
      if (isMediaFragment(frag)) {
        const curSNIdx = frag.sn - trackDetails.startSN;
        const prevFrag = trackDetails.fragments[curSNIdx - 1] as
          | MediaFragment
          | undefined;
        if (
          frag.cc === prevFrag?.cc &&
          !trackDetails.partList?.length &&
          this.fragmentTracker.getState(prevFrag) === FragmentState.NOT_LOADED
        ) {
          frag = prevFrag;
        }
      }
      this.loadFragment(frag, track, targetBufferTime);
    }
  }

  protected loadFragment(
    frag: MediaFragment,
    level: Level,
    targetBufferTime: number,
  ) {
    // Check if fragment is not loaded
    const fragState = this.fragmentTracker.getState(frag);
    if (
      fragState === FragmentState.NOT_LOADED ||
      fragState === FragmentState.PARTIAL
    ) {
      super.loadFragment(frag, level, targetBufferTime);
    }
  }

  get mediaBufferTimeRanges(): Bufferable {
    return new BufferableInstance(
      this.tracksBuffered[this.currentTrackId] || [],
    );
  }
}

class BufferableInstance implements Bufferable {
  public readonly buffered: TimeRanges;

  constructor(timeranges: TimeRange[]) {
    const getRange = (
      name: 'start' | 'end',
      index: number,
      length: number,
    ): number => {
      index = index >>> 0;
      if (index > length - 1) {
        throw new DOMException(
          `Failed to execute '${name}' on 'TimeRanges': The index provided (${index}) is greater than the maximum bound (${length})`,
        );
      }
      return timeranges[index][name];
    };
    this.buffered = {
      get length() {
        return timeranges.length;
      },
      end(index: number): number {
        return getRange('end', index, timeranges.length);
      },
      start(index: number): number {
        return getRange('start', index, timeranges.length);
      },
    };
  }
}
