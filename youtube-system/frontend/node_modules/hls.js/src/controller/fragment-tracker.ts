import { Events } from '../events';
import {
  type Fragment,
  isMediaFragment,
  type MediaFragment,
  type Part,
} from '../loader/fragment';
import { userAgentChromeVersion } from '../utils/user-agent';
import type Hls from '../hls';
import type { SourceBufferName } from '../types/buffer';
import type { ComponentAPI } from '../types/component-api';
import type {
  BufferAppendedData,
  FragBufferedData,
  FragLoadedData,
} from '../types/events';
import type {
  FragmentBufferedRange,
  FragmentEntity,
  FragmentTimeRange,
} from '../types/fragment-tracker';
import type { PlaylistLevelType } from '../types/loader';

export const enum FragmentState {
  NOT_LOADED = 'NOT_LOADED',
  APPENDING = 'APPENDING',
  PARTIAL = 'PARTIAL',
  OK = 'OK',
}

export class FragmentTracker implements ComponentAPI {
  private activePartLists: { [key in PlaylistLevelType]?: Part[] } =
    Object.create(null);
  private endListFragments: { [key in PlaylistLevelType]?: FragmentEntity } =
    Object.create(null);
  private fragments: Partial<Record<string, FragmentEntity>> =
    Object.create(null);
  private timeRanges:
    | {
        [key in SourceBufferName]?: TimeRanges;
      }
    | null = Object.create(null);

  private bufferPadding: number = 0.2;
  private hls: Hls | null;
  private hasGaps: boolean = false;

  constructor(hls: Hls) {
    this.hls = hls;

    this._registerListeners();
  }

  private _registerListeners() {
    const { hls } = this;
    if (hls) {
      hls.on(Events.MANIFEST_LOADING, this.onManifestLoading, this);
      hls.on(Events.BUFFER_APPENDED, this.onBufferAppended, this);
      hls.on(Events.FRAG_BUFFERED, this.onFragBuffered, this);
      hls.on(Events.FRAG_LOADED, this.onFragLoaded, this);
    }
  }

  private _unregisterListeners() {
    const { hls } = this;
    if (hls) {
      hls.off(Events.MANIFEST_LOADING, this.onManifestLoading, this);
      hls.off(Events.BUFFER_APPENDED, this.onBufferAppended, this);
      hls.off(Events.FRAG_BUFFERED, this.onFragBuffered, this);
      hls.off(Events.FRAG_LOADED, this.onFragLoaded, this);
    }
  }

  public destroy() {
    this._unregisterListeners();
    // @ts-ignore
    this.hls =
      // @ts-ignore
      this.fragments =
      // @ts-ignore
      this.activePartLists =
      // @ts-ignore
      this.endListFragments =
      this.timeRanges =
        null;
  }

  /**
   * Return a Fragment or Part with an appended range that matches the position and levelType
   * Otherwise, return null
   */
  public getAppendedFrag(
    position: number,
    levelType: PlaylistLevelType,
  ): MediaFragment | Part | null {
    const activeParts = this.activePartLists[levelType];
    if (activeParts) {
      for (let i = activeParts.length; i--; ) {
        const activePart = activeParts[i];
        if (!activePart as any) {
          break;
        }
        if (
          activePart.start <= position &&
          position <= activePart.end &&
          activePart.loaded
        ) {
          return activePart;
        }
      }
    }
    return this.getBufferedFrag(position, levelType);
  }

  /**
   * Return a buffered Fragment that matches the position and levelType.
   * A buffered Fragment is one whose loading, parsing and appending is done (completed or "partial" meaning aborted).
   * If not found any Fragment, return null
   */
  public getBufferedFrag(
    position: number,
    levelType: PlaylistLevelType,
  ): MediaFragment | null {
    return this.getFragAtPos(position, levelType, true);
  }

  public getFragAtPos(
    position: number,
    levelType: PlaylistLevelType,
    buffered?: boolean,
  ): MediaFragment | null {
    const { fragments } = this;
    const keys = Object.keys(fragments);
    for (let i = keys.length; i--; ) {
      const fragmentEntity = fragments[keys[i]];
      if (
        fragmentEntity?.body.type === levelType &&
        (!buffered || fragmentEntity.buffered)
      ) {
        const frag = fragmentEntity.body;
        if (frag.start <= position && position <= frag.end) {
          return frag;
        }
      }
    }
    return null;
  }

  /**
   * Partial fragments effected by coded frame eviction will be removed
   * The browser will unload parts of the buffer to free up memory for new buffer data
   * Fragments will need to be reloaded when the buffer is freed up, removing partial fragments will allow them to reload(since there might be parts that are still playable)
   */
  public detectEvictedFragments(
    elementaryStream: SourceBufferName,
    timeRange: TimeRanges,
    playlistType: PlaylistLevelType,
    appendedFrag?: MediaFragment | null,
    appendedPart?: Part | null,
    removeAppending?: boolean,
  ) {
    if (this.timeRanges) {
      this.timeRanges[elementaryStream] = timeRange;
    }
    // Check if any flagged fragments have been unloaded
    // excluding anything newer than appendedPartSn
    const appendedPartSn = appendedPart?.fragment.sn || -1;
    Object.keys(this.fragments).forEach((key) => {
      const fragmentEntity = this.fragments[key];
      if (!fragmentEntity || !this.hls) {
        return;
      }
      const frag = fragmentEntity.body;
      if (appendedPartSn >= frag.sn) {
        return;
      }
      if (
        !fragmentEntity.buffered &&
        (!fragmentEntity.loaded || removeAppending)
      ) {
        if (frag.type === playlistType) {
          this.removeFragment(frag);
        }
        return;
      }
      const esData = fragmentEntity.range[elementaryStream];
      if (!esData) {
        return;
      }
      if (esData.time.length === 0) {
        this.removeFragment(frag);
        return;
      }
      esData.time.some((time: FragmentTimeRange) => {
        const isNotBuffered = !this.isTimeBuffered(
          time.startPTS,
          time.endPTS,
          timeRange,
        );
        if (isNotBuffered) {
          // Unregister partial fragment as it needs to load again to be reused
          this.removeFragment(frag);
        }
        return isNotBuffered;
      });
      // Flush forward buffer in Chrome when PTS overlap detected
      // Workaround https://github.com/video-dev/hls.js/issues/6777 (https://issues.chromium.org/u/1/issues/336839131)
      if (appendedFrag && appendedFrag !== frag && userAgentChromeVersion()) {
        const endPTS = appendedFrag.endPTS;
        const otherStartPTS = frag.startPTS;
        if (endPTS && otherStartPTS && fragmentEntity.range.video) {
          const diff = otherStartPTS - endPTS;
          // overlap is no more than 1/10s
          if (diff < 0 && diff > -0.1) {
            this.removeFragment(frag);
            this.hls.trigger(Events.BUFFER_FLUSHING, {
              // pad removal start to avoid accedental removal of appendedFrag
              startOffset: endPTS + 0.004,
              endOffset: Infinity,
              type: 'video',
            });
          }
        }
      }
    });
  }

  /**
   * Checks if the fragment passed in is loaded in the buffer properly
   * Partially loaded fragments will be registered as a partial fragment
   */
  public detectPartialFragments(data: FragBufferedData) {
    const timeRanges = this.timeRanges;
    const { frag, part, id: playlistType } = data;
    if (!timeRanges || !isMediaFragment(frag)) {
      return;
    }
    const fragKey = getFragmentKey(frag);
    const fragmentEntity = this.fragments[fragKey];
    if (!fragmentEntity || (fragmentEntity.buffered && frag.gap)) {
      return;
    }
    const isFragHint = !frag.relurl;
    Object.keys(timeRanges).forEach((elementaryStream: SourceBufferName) => {
      const streamInfo = frag.elementaryStreams[elementaryStream];
      if (!streamInfo) {
        return;
      }
      const timeRange = timeRanges[elementaryStream] as TimeRanges;
      const partial = isFragHint || streamInfo.partial === true;
      fragmentEntity.range[elementaryStream] = this.getBufferedTimes(
        frag,
        part,
        partial,
        timeRange,
      );
      this.detectEvictedFragments(
        elementaryStream,
        timeRange,
        playlistType,
        frag,
        part,
      );
    });
    fragmentEntity.loaded = null;
    const trackNames = Object.keys(fragmentEntity.range) as SourceBufferName[];
    if (trackNames.length) {
      this.bufferedEnd(fragmentEntity, frag);
      if (!isPartial(fragmentEntity)) {
        // Remove older fragment parts from lookup after frag is tracked as buffered
        this.removeParts(frag.sn - 1, frag.type);
      }
      // Detect nothing buffered for segment append (open-GOP issue #7774)
      if (!part) {
        const minPartialAppend = Math.min(0.004, frag.duration);
        trackNames.some((elementaryStream) => {
          const times = fragmentEntity.range[elementaryStream]?.time;
          const bufferedGap =
            times.length === 0 ||
            (times.length === 1 &&
              times[0].endPTS - times[0].startPTS < minPartialAppend);
          if (bufferedGap) {
            // Segment was appended but it did not change buffer. Mark as gap to prevent loop loading.
            this.addAsGap(frag);
          }
          return bufferedGap;
        });
      }
    } else {
      // remove fragment if nothing was appended
      this.removeFragment(frag);
    }
  }

  public addAsGap(frag: MediaFragment) {
    frag.gap = true;
    this.removeFragment(frag);
    this.fragBuffered(frag, true);
  }

  private bufferedEnd(fragmentEntity: FragmentEntity, frag: MediaFragment) {
    fragmentEntity.buffered = true;
    const endList = (fragmentEntity.body.endList =
      frag.endList || fragmentEntity.body.endList);
    if (endList && !frag.gap) {
      this.endListFragments[fragmentEntity.body.type] = fragmentEntity;
    }
  }

  private removeParts(snToKeep: number, levelType: PlaylistLevelType) {
    const activeParts = this.activePartLists[levelType];
    if (!activeParts) {
      return;
    }
    this.activePartLists[levelType] = filterParts(
      activeParts,
      (part) => part.fragment.sn >= snToKeep,
    );
  }

  public fragBuffered(
    frag: MediaFragment,
    force?: true,
  ): FragmentEntity | undefined {
    const fragKey = getFragmentKey(frag);
    let fragmentEntity = this.fragments[fragKey];
    if (!fragmentEntity && force) {
      fragmentEntity = this.fragments[fragKey] = {
        body: frag,
        appendedPTS: null,
        loaded: null,
        buffered: false,
        range: Object.create(null),
      };
      if (frag.gap) {
        this.hasGaps = true;
      }
    }
    if (fragmentEntity) {
      fragmentEntity.loaded = null;
      this.bufferedEnd(fragmentEntity, frag);
    }
    return fragmentEntity;
  }

  private getBufferedTimes(
    fragment: Fragment,
    part: Part | null,
    partial: boolean,
    timeRange: TimeRanges,
  ): FragmentBufferedRange {
    const buffered: FragmentBufferedRange = {
      time: [],
      partial,
    };
    const startPTS = fragment.start;
    const endPTS = fragment.end;
    const minEndPTS = fragment.minEndPTS || endPTS;
    const maxStartPTS = fragment.maxStartPTS || startPTS;
    for (let i = 0; i < timeRange.length; i++) {
      const startTime = timeRange.start(i) - this.bufferPadding;
      const endTime = timeRange.end(i) + this.bufferPadding;
      if (maxStartPTS >= startTime && minEndPTS <= endTime) {
        // Fragment is entirely contained in buffer
        // No need to check the other timeRange times since it's completely playable
        buffered.time.push({
          startPTS: Math.max(startPTS, timeRange.start(i)),
          endPTS: Math.min(endPTS, timeRange.end(i)),
        });
        break;
      } else if (startPTS < endTime && endPTS > startTime) {
        const start = Math.max(startPTS, timeRange.start(i));
        const end = Math.min(endPTS, timeRange.end(i));
        if (end > start) {
          buffered.partial = true;
          // Check for intersection with buffer
          // Get playable sections of the fragment
          buffered.time.push({
            startPTS: start,
            endPTS: end,
          });
        }
      } else if (endPTS <= startTime) {
        // No need to check the rest of the timeRange as it is in order
        break;
      }
    }
    return buffered;
  }

  /**
   * Gets the partial fragment for a certain time
   */
  public getPartialFragment(time: number): MediaFragment | null {
    let bestFragment: Fragment | null = null;
    let timePadding: number;
    let startTime: number;
    let endTime: number;
    let bestOverlap: number = 0;
    const { bufferPadding, fragments } = this;
    Object.keys(fragments).forEach((key) => {
      const fragmentEntity = fragments[key];
      if (!fragmentEntity) {
        return;
      }
      if (isPartial(fragmentEntity)) {
        startTime = fragmentEntity.body.start - bufferPadding;
        endTime = fragmentEntity.body.end + bufferPadding;
        if (time >= startTime && time <= endTime) {
          // Use the fragment that has the most padding from start and end time
          timePadding = Math.min(time - startTime, endTime - time);
          if (bestOverlap <= timePadding) {
            bestFragment = fragmentEntity.body;
            bestOverlap = timePadding;
          }
        }
      }
    });
    return bestFragment;
  }

  public isEndListAppended(type: PlaylistLevelType): boolean {
    const lastFragmentEntity = this.endListFragments[type];
    return (
      lastFragmentEntity !== undefined &&
      (lastFragmentEntity.buffered || isPartial(lastFragmentEntity))
    );
  }

  public getState(fragment: Fragment): FragmentState {
    const fragKey = getFragmentKey(fragment);
    const fragmentEntity = this.fragments[fragKey];

    if (fragmentEntity) {
      if (!fragmentEntity.buffered) {
        return FragmentState.APPENDING;
      } else if (isPartial(fragmentEntity)) {
        return FragmentState.PARTIAL;
      } else {
        return FragmentState.OK;
      }
    }

    return FragmentState.NOT_LOADED;
  }

  private isTimeBuffered(
    startPTS: number,
    endPTS: number,
    timeRange: TimeRanges,
  ): boolean {
    let startTime;
    let endTime;
    for (let i = 0; i < timeRange.length; i++) {
      startTime = timeRange.start(i) - this.bufferPadding;
      endTime = timeRange.end(i) + this.bufferPadding;
      if (startPTS >= startTime && endPTS <= endTime) {
        return true;
      }

      if (endPTS <= startTime) {
        // No need to check the rest of the timeRange as it is in order
        return false;
      }
    }

    return false;
  }

  private onManifestLoading() {
    this.removeAllFragments();
  }

  private onFragLoaded(event: Events.FRAG_LOADED, data: FragLoadedData) {
    // don't track initsegment (for which sn is not a number)
    // don't track frags used for bitrateTest, they're irrelevant.
    if (!isMediaFragment(data.frag) || data.frag.bitrateTest) {
      return;
    }

    const frag = data.frag as MediaFragment;
    // Fragment entity `loaded` FragLoadedData is null when loading parts
    const loaded = data.part ? null : data;

    const fragKey = getFragmentKey(frag);
    this.fragments[fragKey] = {
      body: frag,
      appendedPTS: null,
      loaded,
      buffered: false,
      range: Object.create(null),
    };
  }

  private onBufferAppended(
    event: Events.BUFFER_APPENDED,
    data: BufferAppendedData,
  ) {
    const { frag, part, timeRanges } = data;
    if (!isMediaFragment(frag)) {
      return;
    }
    const playlistType = frag.type;
    if (part) {
      let activeParts = this.activePartLists[playlistType];
      if (!activeParts) {
        this.activePartLists[playlistType] = activeParts = [];
      }
      activeParts.push(part);
    }
    // Store the latest timeRanges loaded in the buffer
    this.timeRanges = timeRanges;
  }

  private onFragBuffered(event: Events.FRAG_BUFFERED, data: FragBufferedData) {
    this.detectPartialFragments(data);
  }

  private hasFragment(fragment: Fragment): boolean {
    const fragKey = getFragmentKey(fragment);
    return !!this.fragments[fragKey];
  }

  public hasFragments(type?: PlaylistLevelType): boolean {
    const { fragments } = this;
    const keys = Object.keys(fragments);
    if (!type) {
      return keys.length > 0;
    }
    for (let i = keys.length; i--; ) {
      const fragmentEntity = fragments[keys[i]];
      if (fragmentEntity?.body.type === type) {
        return true;
      }
    }
    return false;
  }

  public hasParts(type: PlaylistLevelType): boolean {
    return !!this.activePartLists[type]?.length;
  }

  /**
   * Returns the end position needed to free at least `bytesNeeded` from the
   * back buffer, or 0 if not enough data is available. Walks buffered
   * fragments in key order, accumulating byte sizes using stats.loaded,
   * byteLength, or a bitrate estimate as fallback.
   */
  public getBackBufferEvictionEnd(
    beforePosition: number,
    levelType: PlaylistLevelType,
    bytesNeeded: number,
  ): number {
    const { fragments } = this;

    // Collect back buffer fragments with known byte sizes
    let bytesFreed = 0;
    let evictEnd = 0;
    const keys = Object.keys(fragments);
    for (let i = 0; i < keys.length; i++) {
      const entity = fragments[keys[i]];
      if (!entity || !entity.buffered || entity.body.type !== levelType) {
        continue;
      }
      const frag = entity.body;
      if (frag.gap) {
        // do not evict media when gaps are detected
        return 0;
      }
      // Use stats.loaded (always set after load) with byteLength as fallback
      const bytes =
        (frag.hasStats && frag.stats.loaded) ||
        frag.byteLength ||
        (frag.bitrate && frag.bitrate * 8 * frag.duration);
      if (frag.end <= beforePosition && bytes) {
        bytesFreed += bytes;
        evictEnd = Math.max(evictEnd, frag.end);
        if (bytesFreed >= bytesNeeded) {
          return evictEnd;
        }
      }
    }

    // Not enough to fully cover bytesNeeded, return what we have
    return evictEnd > 0 ? evictEnd : 0;
  }

  public removeFragmentsInRange(
    start: number,
    end: number,
    playlistType: PlaylistLevelType,
    withGapOnly?: boolean,
    unbufferedOnly?: boolean,
  ) {
    if (withGapOnly && !this.hasGaps) {
      return;
    }
    Object.keys(this.fragments).forEach((key) => {
      const fragmentEntity = this.fragments[key];
      if (!fragmentEntity) {
        return;
      }
      const frag = fragmentEntity.body;
      if (frag.type !== playlistType || (withGapOnly && !frag.gap)) {
        return;
      }
      if (
        frag.start < end &&
        frag.end > start &&
        (fragmentEntity.buffered || unbufferedOnly)
      ) {
        this.removeFragment(frag);
      }
    });
  }

  public removeFragment(fragment: Fragment) {
    const fragKey = getFragmentKey(fragment);
    fragment.clearElementaryStreamInfo();
    const activeParts = this.activePartLists[fragment.type];
    if (activeParts) {
      const snToRemove = fragment.sn;
      this.activePartLists[fragment.type] = filterParts(
        activeParts,
        (part) => part.fragment.sn !== snToRemove,
      );
    }
    delete this.fragments[fragKey];
    if (fragment.endList) {
      delete this.endListFragments[fragment.type];
    }
  }

  public removeAllFragments() {
    this.fragments = Object.create(null);
    this.endListFragments = Object.create(null);
    this.activePartLists = Object.create(null);
    this.hasGaps = false;
    const partlist = this.hls?.latestLevelDetails?.partList;
    if (partlist) {
      partlist.forEach((part) => part.clearElementaryStreamInfo());
    }
  }
}

function isPartial(fragmentEntity: FragmentEntity): boolean {
  return (
    fragmentEntity.buffered &&
    !!(
      fragmentEntity.body.gap ||
      fragmentEntity.range.video?.partial ||
      fragmentEntity.range.audio?.partial ||
      fragmentEntity.range.audiovideo?.partial ||
      fragmentEntity.range.subs?.partial
    )
  );
}

function getFragmentKey(fragment: Fragment): string {
  return `${fragment.type}_${fragment.level}_${fragment.sn}`;
}

function filterParts(partList: Part[], predicate: (part: Part) => boolean) {
  return partList.filter((part) => {
    const keep = predicate(part);
    if (!keep) {
      part.clearElementaryStreamInfo();
    }
    return keep;
  });
}
