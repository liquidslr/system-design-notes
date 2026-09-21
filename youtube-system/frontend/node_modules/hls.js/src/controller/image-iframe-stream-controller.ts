import { State } from './base-stream-controller';
import { IFrameStreamController } from './iframe-stream-controller';
import { ErrorDetails, ErrorTypes } from '../errors';
import { Events } from '../events';
import {
  type Fragment,
  mediaFragmentsAreEqual,
  type Part,
} from '../loader/fragment';
import { findBox } from '../utils/mp4-tools';
import type { MediaFragment } from '../loader/fragment';
import type { RemuxedTrack } from '../types/remuxer';
import type { ChunkMetadata } from '../types/transmuxer';

export class ImageIFrameStreamController extends IFrameStreamController {
  private _img?: HTMLImageElement;
  private queued?: [time: number];
  // Image data extracted from fragments is cached instead (bufferFragmentData)
  protected cacheFragmentData: boolean = false;

  get image(): HTMLImageElement | undefined {
    return this._img;
  }

  set image(value: HTMLImageElement | undefined) {
    const src = this._img?.src;
    if (src) {
      self.URL.revokeObjectURL(src);
    }
    this._img = value;
  }

  loadMediaAt(time: number) {
    if (!this.hls) {
      return;
    }
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
      this.media ||= {} as any;
      this.tick();
      // If segment is already loaded, state will remain IDLE. Update image and/or emit buffered events.
      if (this.state === State.IDLE) {
        const frag = this.getBufferedAt(time);
        if (frag) {
          this.fragCurrent = frag;
          this.updateImage(frag, null);
        }
      }
    } else {
      const fragCurrent = this.fragCurrent;
      if (
        !fragCurrent ||
        (time >= fragCurrent.start && time < fragCurrent.end)
      ) {
        this.queued = [adjustedTime];
      }
    }
  }

  private updateImage(
    frag: MediaFragment,
    part: Part | null,
    chunkMeta?: ChunkMetadata,
  ) {
    const imageBytesView = frag.data;
    if (!imageBytesView) {
      this.fragmentTracker.removeFragment(frag);
    }
    const image = this._img;
    if (image && imageBytesView) {
      const now = self.performance.now();
      const stats = part ? part.stats : frag.stats;
      stats.buffering.start = frag.stats.buffering.start = now;
      image.onload = () => {
        if (!this.hls) {
          return;
        }
        const level = this.hls.levels[frag.level];
        if (level?.fragmentError) {
          level.fragmentError = 0;
          frag.stats.retry = 0;
        }
        const now = self.performance.now();
        const stats = part ? part.stats : frag.stats;
        stats.buffering.end = frag.stats.buffering.end = now;
        this.hls.trigger(Events.FRAG_BUFFERED, {
          frag,
          part,
          stats,
          id: frag.type,
          chunkMeta,
        });
      };
      image.onerror = () => {
        this.handleError('Image decode error', frag, part, chunkMeta);
      };
      const src = image.src;
      if (src) {
        self.URL.revokeObjectURL(src);
      }
      const blob = new Blob([imageBytesView], {
        type: 'image/jpeg',
      });
      image.src = self.URL.createObjectURL(blob);
    } else {
      this.state = State.STOPPED;
      this.processQueued();
    }
  }

  private processQueued() {
    const queued = this.queued;
    this.queued = undefined;
    if (queued) {
      this.loadMediaAt.apply(this, queued);
    }
  }

  private handleError(
    message: string,
    frag: Fragment,
    part?: Part | null,
    chunkMeta?: ChunkMetadata,
  ) {
    if (!this.hls) {
      return;
    }
    const error = new Error(message);
    this.hls.trigger(Events.ERROR, {
      type: ErrorTypes.MEDIA_ERROR,
      details: ErrorDetails.FRAG_PARSING_ERROR,
      chunkMeta,
      frag,
      part,
      fatal: false,
      error,
      err: error,
    });
  }

  // overrides
  protected _bufferInitSegment() {}

  protected bufferFragmentData(
    data: RemuxedTrack,
    frag: Fragment,
    part: Part | null,
    chunkMeta: ChunkMetadata,
  ) {
    super.bufferFragmentData(data, frag, part, chunkMeta, true);
    const results = findBox(new Uint8Array(data.data1), [
      'mdat',
    ]) as Uint8Array<ArrayBuffer>[];
    if (results.length === 0) {
      this.handleError('Could not find I-Frame mdat', frag, part, chunkMeta);
      return;
    }
    const fragment = frag as MediaFragment;
    this.cacheSet(fragment, results[0]);
    this.updateImage(fragment, part, chunkMeta);
  }

  protected fragBufferedComplete(frag: Fragment, part: Part | null) {
    this.fragmentTracker.fragBuffered(frag as MediaFragment, true);
    super.fragBufferedComplete(frag, part);
    this.processQueued();
  }

  protected checkFragPlaying(): boolean {
    const currentTime = this.fragPrevious?.start;
    if (currentTime !== undefined) {
      const fragPlayingCurrent = this.getAppendedFrag(currentTime);
      if (
        fragPlayingCurrent &&
        !mediaFragmentsAreEqual(fragPlayingCurrent, this.fragPlaying)
      ) {
        this.fragPlaying = fragPlayingCurrent;
        return true;
      }
    }
    return false;
  }

  getMainFwdBufferInfo() {
    return {
      len: 0,
      start: this.playhead,
      end: this.playhead,
      bufferedIndex: -1,
    };
  }
}
