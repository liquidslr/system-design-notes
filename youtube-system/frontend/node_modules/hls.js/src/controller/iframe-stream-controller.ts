import { State } from './base-stream-controller';
import { FragmentState } from './fragment-tracker';
import StreamController from './stream-controller';
import { Events } from '../events';
import { isMediaFragment } from '../loader/fragment';
import { LoadStats } from '../loader/load-stats';
import { PlaylistLevelType } from '../types/loader';
import { BufferHelper } from '../utils/buffer-helper';
import { timeRangesToString } from '../utils/time-ranges';
import type { Fragment, MediaFragment, Part } from '../loader/fragment';
import type { LevelDetails } from '../loader/level-details';
import type { FragLoadedData } from '../types/events';
import type { Level } from '../types/level';
import type { TimestampOffset } from '../utils/timescale-conversion';

export type LoadMediaAtOptions = { seekOnAppend: boolean };

export class IFrameStreamController extends StreamController {
  private currentOp?: [time: number, options: LoadMediaAtOptions];
  private nextOp?: [time: number, options: LoadMediaAtOptions];
  protected cached: MediaFragment[] = [];
  protected cachedSize = 0;
  // Replay cache (image controller caches decoded image data instead)
  protected cacheFragmentData: boolean = true;
  initDetails?: LevelDetails | null;

  setInitPts(initPTS: TimestampOffset[]) {
    this.initPTS = initPTS.slice();
  }

  loadMediaAt(time: number, options: LoadMediaAtOptions) {
    if (!this.hls) {
      return;
    }
    const { seekOnAppend } = options;
    const adjustedTime = time + this.timelineOffset;
    this.nextLoadPosition = this.lastCurrentTime = adjustedTime;
    this.startPosition = time;
    switch (this.state) {
      case State.STOPPED:
      case State.ENDED:
      case State.ERROR:
        this.state = State.IDLE;
    }
    if (this.state === State.IDLE) {
      this.hls.resumeBuffering();
      this.tick();
      this.currentOp = [adjustedTime, options];
    } else {
      // Queue op (replacing any pending) to run once the active load completes
      this.nextOp = [adjustedTime, options];
    }
    // This operation supersedes any seek scheduled for end of stream
    this.hls.off(Events.BUFFERED_TO_END, this.onBufferedToEnd);
    const media = this.media;
    if (seekOnAppend && media) {
      const seeking = this.seekTo(adjustedTime);
      if (seeking) {
        this.currentOp = [adjustedTime, options];
        this.nextOp = undefined;
        this.flushPipeline(adjustedTime, true);
      }
    }
  }

  private seekTo(time: number): boolean {
    const media = this.media;
    if (media) {
      // Clamp to playlist edge, not media.duration (truncated by endOfStream())
      const edge = this.getLevelDetails()?.edge;
      const end = edge !== undefined ? edge : media.duration;
      if (time >= end) {
        time = end - 0.01;
      }
      const bufferInfo = BufferHelper.bufferInfo(media, time, 0);
      const hasEnough = bufferInfo.len > 0 && this.getBufferedAt(time);
      if (hasEnough) {
        media.currentTime = time;
        return true;
      }
    }
    return false;
  }

  protected getBufferedAt(time: number): MediaFragment | null {
    return this.fragmentTracker.getBufferedFrag(time, PlaylistLevelType.MAIN);
  }

  // Retain fragment data for re-buffering (up to iframeCacheLimit bytes, LRU)
  protected cacheSet(frag: MediaFragment, data: Uint8Array<ArrayBuffer>) {
    if (!this.hls) {
      return;
    }
    frag.data = data;
    const cache = this.cached;
    cache.push(frag);
    this.cachedSize += data.buffer.byteLength;
    const iframeCacheLimit = this.hls.config.iframeCacheLimit;
    while (this.cachedSize > iframeCacheLimit && cache.length > 1) {
      const evicted = cache.shift()!;
      if (evicted.data) {
        this.cachedSize -= evicted.data.byteLength;
        evicted.data = undefined;
      } else {
        // Fragment was removed. Re-evaluate size.
        this.cached = cache.filter((frag) => !!frag.data);
        this.cachedSize = cache.reduce(
          (acc, { data }) => (data ? data.buffer.byteLength : 0),
          0,
        );
        break;
      }
    }
  }

  protected onHandlerDestroying() {
    this.cached.length = 0;
    this.cachedSize = 0;
    super.onHandlerDestroying();
  }

  // overrides
  protected _handleFragmentLoadProgress(data: FragLoadedData) {
    const frag = data.frag;
    const { part, payload } = data;
    if (
      this.cacheFragmentData &&
      !part &&
      payload?.byteLength &&
      !frag.data &&
      isMediaFragment(frag)
    ) {
      // Cache a pristine copy (the remuxer rewrites fragment data in place)
      this.cacheSet(frag, new Uint8Array(payload.slice(0)));
    }
    super._handleFragmentLoadProgress(data);
  }

  protected loadFragment(
    frag: MediaFragment,
    level: Level,
    targetBufferTime: number,
  ) {
    const fragState = this.fragmentTracker.getState(frag);
    if (
      (fragState === FragmentState.NOT_LOADED ||
        fragState === FragmentState.PARTIAL) &&
      this.canReplayCached(frag)
    ) {
      this.replayCachedFragment(frag);
      return;
    }
    super.loadFragment(frag, level, targetBufferTime);
  }

  // Cached data can replay unless decryption needs a key that is not loaded
  private canReplayCached(frag: MediaFragment): boolean {
    if (!this.cacheFragmentData || !frag.data?.byteLength) {
      return false;
    }
    const decryptdata = frag.decryptdata;
    return decryptdata?.keyFormat !== 'identity' || !!decryptdata.key;
  }

  private replayCachedFragment(frag: MediaFragment) {
    // The remuxer rewrites fragment data in place: transmux a copy
    const payload = frag.data!.slice().buffer;
    this.log(
      `Buffering cached ${frag.type} sn: ${frag.sn} of level ${frag.level} (${payload.byteLength} bytes)`,
    );
    this.fragCurrent = frag;
    this.startFragRequested = true;
    const stats = (frag.stats = new LoadStats());
    stats.loading.start =
      stats.loading.first =
      stats.loading.end =
        self.performance.now();
    stats.loaded = stats.total = payload.byteLength;
    stats.chunkCount = 1;
    this.state = State.FRAG_LOADING;
    const data: FragLoadedData = {
      frag,
      part: null,
      payload,
      networkDetails: null,
    };
    this._handleFragmentLoadProgress(data);
    // FRAG_LOADED registers the fragment with the fragment tracker
    this.hls.trigger(Events.FRAG_LOADED, data);
    this._handleFragmentLoadComplete(data);
  }

  protected fragBufferedComplete(frag: Fragment, part: Part | null) {
    super.fragBufferedComplete(frag, part);

    const { currentOp, nextOp } = this;
    this.currentOp = this.nextOp = undefined;
    this.state = State.STOPPED;
    if (currentOp?.[1].seekOnAppend) {
      this.flushPipeline(currentOp[0], !nextOp);
      if (!this.seekTo(currentOp[0])) {
        this.log(
          `Could not seek to ${currentOp[0]} after fragment buffered (superseded or flushed) buffer: ${this.media ? timeRangesToString(BufferHelper.getBuffered(this.media)) : 'none'}`,
        );
      }
    }
    if (nextOp) {
      this.loadMediaAt.apply(this, nextOp);
    }
  }

  private flushPipeline(time: number, removeDisjointRanges: boolean) {
    if (removeDisjointRanges) {
      // Remove buffered ranges beyond the target's and signal EOS before
      // seeking: a lone keyframe followed by a gap does not render
      const media = this.media;
      if (media) {
        const bufferInfo = BufferHelper.bufferInfo(media, time, 0);
        const nextRangeStart = bufferInfo.len ? bufferInfo.nextStart : 0;
        if (nextRangeStart) {
          // Evict now so queued operations do not seek into removed ranges
          this.fragmentTracker.removeFragmentsInRange(
            nextRangeStart,
            Infinity,
            PlaylistLevelType.MAIN,
          );
          this.flushMainBuffer(nextRangeStart, Infinity);
        }
      }
      // (onBufferedToEnd re-runs the seek if EOS completes after it)
      this.hls.once(Events.BUFFERED_TO_END, this.onBufferedToEnd);
    }
    this.hls.trigger(Events.BUFFER_EOS, { type: 'video' });
  }

  private onBufferedToEnd = () => {
    const media = this.media;
    if (media?.seeking) {
      // Re-run the pending seek now that the MediaSource has ended
      // eslint-disable-next-line no-self-assign
      media.currentTime = media.currentTime;
    }
  };

  get playhead(): number {
    return this.nextLoadPosition;
  }

  startLoad() {
    if (!this.startFragRequested) {
      const hlsIFrames = this.hls;
      hlsIFrames.nextLoadLevel =
        hlsIFrames.startLevel === -1 ? 0 : hlsIFrames.firstAutoLevel;
    }
  }
  // public getLevelDetails
  protected seekToStartPos() {}
  protected setStartPosition() {}
  // Seeking is always initiated by this controller; ignore media seek events.
  protected onMediaSeeking = () => {};

  protected alignPlaylists(
    details: LevelDetails,
    previousDetails: LevelDetails | undefined,
    switchDetails: LevelDetails | undefined,
  ): number {
    const initDetails = this.initDetails;
    this.initDetails = null;
    return super.alignPlaylists(
      details,
      previousDetails,
      switchDetails || initDetails || undefined,
    );
  }

  getMainFwdBufferInfo() {
    const t = this.playhead;
    const bufferedFragAtPos = this.getBufferedAt(t);
    if (bufferedFragAtPos) {
      const len = bufferedFragAtPos.duration;
      return { len, start: t, end: t + len, bufferedIndex: -1 };
    }
    return { len: 0, start: t, end: t, bufferedIndex: -1 };
  }

  protected _streamEnded() {
    const t = this.playhead;
    const bufferedFragAtPos = this.fragmentTracker.getBufferedFrag(
      t,
      PlaylistLevelType.MAIN,
    );
    return !!bufferedFragAtPos?.endList;
  }
}
