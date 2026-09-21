/*
 * cap stream level to media size dimension controller
 */

import { Events } from '../events';
import type StreamController from './stream-controller';
import type Hls from '../hls';
import type { ComponentAPI } from '../types/component-api';
import type {
  BufferCodecsData,
  FPSDropLevelCappingData,
  ManifestParsedData,
  MediaAttachingData,
} from '../types/events';
import type { Level } from '../types/level';

type RestrictedLevel = { width: number; height: number; bitrate: number };
class CapLevelController implements ComponentAPI {
  private hls: Hls | null = null;
  private autoLevelCapping: number;
  private media: HTMLVideoElement | null;
  private restrictedLevels: RestrictedLevel[];
  private timer?: number;
  private observer?: ResizeObserver;
  private clientRect: { width: number; height: number } | null;
  private streamController?: StreamController;

  constructor(hls: Hls) {
    this.hls = hls;
    this.autoLevelCapping = Number.POSITIVE_INFINITY;
    this.media = null;
    this.restrictedLevels = [];
    this.clientRect = null;

    this.registerListeners();
  }

  public setStreamController(streamController: StreamController) {
    this.streamController = streamController;
  }

  public destroy() {
    if (this.hls) {
      this.unregisterListener();
    }
    if (this.timer || this.observer) {
      this.stopCapping();
    }
    this.media = this.clientRect = this.hls = null;
    // @ts-ignore
    this.streamController = undefined;
  }

  protected registerListeners() {
    const { hls } = this;
    if (hls) {
      hls.on(Events.FPS_DROP_LEVEL_CAPPING, this.onFpsDropLevelCapping, this);
      hls.on(Events.MEDIA_ATTACHING, this.onMediaAttaching, this);
      hls.on(Events.MANIFEST_PARSED, this.onManifestParsed, this);
      hls.on(Events.LEVELS_UPDATED, this.onLevelsUpdated, this);
      hls.on(Events.BUFFER_CODECS, this.onBufferCodecs, this);
      hls.on(Events.MEDIA_DETACHING, this.onMediaDetaching, this);
    }
  }

  protected unregisterListener() {
    const { hls } = this;
    if (hls) {
      hls.off(Events.FPS_DROP_LEVEL_CAPPING, this.onFpsDropLevelCapping, this);
      hls.off(Events.MEDIA_ATTACHING, this.onMediaAttaching, this);
      hls.off(Events.MANIFEST_PARSED, this.onManifestParsed, this);
      hls.off(Events.LEVELS_UPDATED, this.onLevelsUpdated, this);
      hls.off(Events.BUFFER_CODECS, this.onBufferCodecs, this);
      hls.off(Events.MEDIA_DETACHING, this.onMediaDetaching, this);
    }
  }

  protected onFpsDropLevelCapping(
    event: Events.FPS_DROP_LEVEL_CAPPING,
    data: FPSDropLevelCappingData,
  ) {
    if (!this.hls) {
      return;
    }
    // Don't add a restricted level more than once
    const level = this.hls.levels[data.droppedLevel];
    if (this.isLevelAllowed(level)) {
      this.restrictedLevels.push({
        bitrate: level.bitrate,
        height: level.height,
        width: level.width,
      });
    }
  }

  protected onMediaAttaching(
    event: Events.MEDIA_ATTACHING,
    data: MediaAttachingData,
  ) {
    const media = data.media;
    this.clientRect = null;
    if (!this.hls) {
      return;
    }
    if (media instanceof HTMLVideoElement) {
      this.media = media;
      if (this.hls.config.capLevelToPlayerSize) {
        this.observe();
      }
    } else {
      this.media = null;
    }
    if ((this.timer || this.observer) && this.hls.levels.length > 1) {
      this.detectPlayerSize();
    }
  }

  protected onManifestParsed(
    event: Events.MANIFEST_PARSED,
    data: ManifestParsedData,
  ) {
    this.restrictedLevels = [];
    if (data.video) {
      // Start capping immediately if the manifest has signaled video codecs
      this.startCapping();
    }
    this.onLevelsUpdated();
  }

  private onLevelsUpdated() {
    if (!this.hls) {
      return;
    }
    if (
      (this.timer || this.observer) &&
      (Number.isFinite(this.autoLevelCapping) || this.clientRect)
    ) {
      // Update capped level index when levels change (or stop observing if length is 1)
      this.detectPlayerSize();
    } else if (this.observer === undefined && this.timer === undefined) {
      const levels = this.hls.levels;
      // Restart observing if length increases
      if (levels.length > 1 && levels.some((level) => !!level.videoCodec)) {
        this.startCapping();
      }
    }
  }

  // Only activate capping when playing a video stream; otherwise, multi-bitrate audio-only streams will be restricted
  // to the first level
  protected onBufferCodecs(
    event: Events.BUFFER_CODECS,
    data: BufferCodecsData,
  ) {
    if (data.video) {
      // If the manifest did not signal a video codec capping has been deferred until we're certain video is present
      this.startCapping();
    }
  }

  protected onMediaDetaching() {
    this.stopCapping();
    this.media = null;
  }

  detectPlayerSize() {
    if (this.media) {
      if (this.mediaHeight <= 0 || this.mediaWidth <= 0 || !this.hls) {
        this.clientRect = null;
        return;
      }
      const levels = this.hls.levels;
      if (levels.length > 1) {
        const hls = this.hls;
        const maxLevel = this.getMaxLevel(levels.length - 1);
        if (maxLevel !== this.autoLevelCapping) {
          hls.logger.log(
            `Setting autoLevelCapping to ${maxLevel}: ${levels[maxLevel].height}p@${levels[maxLevel].bitrate} for media ${this.mediaWidth}x${this.mediaHeight}`,
          );
        }
        hls.autoLevelCapping = maxLevel;
        if (
          hls.autoLevelEnabled &&
          hls.autoLevelCapping > this.autoLevelCapping &&
          this.streamController
        ) {
          // if auto level capping has a higher value for the previous one, flush the buffer using nextLevelSwitch
          // usually happen when the user go to the fullscreen mode.
          this.streamController.nextLevelSwitch();
        }
        this.autoLevelCapping = hls.autoLevelCapping;
      } else if (levels.length === 1) {
        this.stopCapping();
      }
    }
  }

  /*
   * returns level should be the one with the dimensions equal or greater than the media (player) dimensions (so the video will be downscaled)
   */
  getMaxLevel(capLevelIndex: number): number {
    if (!this.hls) {
      return -1;
    }
    const levels = this.hls.levels;
    if (!levels.length) {
      return -1;
    }

    const validLevels = levels.filter(
      (level, index) => this.isLevelAllowed(level) && index <= capLevelIndex,
    );
    if (!this.observer) {
      this.clientRect = null;
    }
    return CapLevelController.getMaxLevelByMediaSize(
      validLevels,
      this.mediaWidth,
      this.mediaHeight,
    );
  }

  private observe() {
    const ResizeObserver = self.ResizeObserver;
    if (ResizeObserver) {
      this.observer = new ResizeObserver((entries) => {
        const bounds = entries[0]?.contentRect;
        if (bounds) {
          this.clientRect = bounds;
          this.detectPlayerSize();
        }
      });
    }
    if (this.observer && this.media) {
      this.observer.observe(this.media);
    }
  }

  startCapping() {
    if (this.timer || this.observer || !this.hls?.config.capLevelToPlayerSize) {
      // Don't reset capping if started twice; this can happen if the manifest signals a video codec
      return;
    }
    self.clearInterval(this.timer);
    this.timer = undefined;
    this.autoLevelCapping = Number.POSITIVE_INFINITY;
    this.observe();
    if (!this.observer) {
      this.timer = self.setInterval(this.detectPlayerSize.bind(this), 1000);
    }
    this.detectPlayerSize();
  }

  stopCapping() {
    this.restrictedLevels = [];
    this.autoLevelCapping = Number.POSITIVE_INFINITY;
    if (this.timer) {
      self.clearInterval(this.timer);
      this.timer = undefined;
    }
    if (this.observer) {
      this.observer.disconnect();
      this.observer = undefined;
    }
  }

  getDimensions(): { width: number; height: number } {
    if (this.clientRect) {
      return this.clientRect;
    }
    const media = this.media;
    const boundsRect = {
      width: 0,
      height: 0,
    };

    if (media) {
      const clientRect = media.getBoundingClientRect();
      boundsRect.width = clientRect.width;
      boundsRect.height = clientRect.height;
      if (!boundsRect.width && !boundsRect.height) {
        // When the media element has no width or height (equivalent to not being in the DOM),
        // then use its width and height attributes (media.width, media.height)
        boundsRect.width =
          clientRect.right - clientRect.left || media.width || 0;
        boundsRect.height =
          clientRect.bottom - clientRect.top || media.height || 0;
      }
    }
    this.clientRect = boundsRect;
    return boundsRect;
  }

  get mediaWidth(): number {
    return this.getDimensions().width * this.contentScaleFactor;
  }

  get mediaHeight(): number {
    return this.getDimensions().height * this.contentScaleFactor;
  }

  get contentScaleFactor(): number {
    let pixelRatio = 1;
    if (!this.hls) {
      return pixelRatio;
    }
    const { ignoreDevicePixelRatio, maxDevicePixelRatio } = this.hls.config;
    if (!ignoreDevicePixelRatio) {
      try {
        pixelRatio = self.devicePixelRatio;
      } catch (e) {
        /* no-op */
      }
    }
    return Math.min(pixelRatio, maxDevicePixelRatio);
  }

  private isLevelAllowed(level: Level): boolean {
    const restrictedLevels = this.restrictedLevels;
    return !restrictedLevels.some((restrictedLevel) => {
      return (
        level.bitrate === restrictedLevel.bitrate &&
        level.width === restrictedLevel.width &&
        level.height === restrictedLevel.height
      );
    });
  }

  static getMaxLevelByMediaSize(
    levels: Array<Level>,
    width: number,
    height: number,
  ): number {
    if (!levels?.length) {
      return -1;
    }

    // Levels can have the same dimensions but differing bandwidths - since levels are ordered, we can look to the next
    // to determine whether we've chosen the greatest bandwidth for the media's dimensions
    const atGreatestBandwidth = (
      curLevel: Level,
      nextLevel: Level | undefined,
    ) => {
      if (!nextLevel) {
        return true;
      }

      return (
        curLevel.width !== nextLevel.width ||
        curLevel.height !== nextLevel.height
      );
    };

    // If we run through the loop without breaking, the media's dimensions are greater than every level, so default to
    // the max level
    let maxLevelIndex = levels.length - 1;
    // Prevent changes in aspect-ratio from causing capping to toggle back and forth
    const squareSize = Math.max(width, height);
    for (let i = 0; i < levels.length; i += 1) {
      const level = levels[i];
      if (
        (level.width >= squareSize || level.height >= squareSize) &&
        atGreatestBandwidth(level, levels[i + 1])
      ) {
        maxLevelIndex = i;
        break;
      }
    }

    return maxLevelIndex;
  }
}

export default CapLevelController;
