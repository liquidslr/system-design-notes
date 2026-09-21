import {
  IFrameStreamController,
  type LoadMediaAtOptions,
} from './iframe-stream-controller';
import { ImageIFrameStreamController } from './image-iframe-stream-controller';
import { Events } from '../events';
import { type LoaderStats, PlaylistLevelType } from '../types/loader';
import { Logger } from '../utils/logger';
import { getVideoPreference } from '../utils/rendition-helper';
import type { HlsConfig } from '../config';
import type Hls from '../hls';
import type { LevelDetails } from '../loader/level-details';
import type {
  FragBufferedData,
  InitPTSFoundData,
  LevelsUpdatedData,
  ManifestLoadedData,
} from '../types/events';
import type { Level, LevelParsed, VariableMap } from '../types/level';
import type { TimestampOffset } from '../utils/timescale-conversion';

const PRELOAD_IFRAME_PLAYLISTS_AFTER_BUFFER_SECONDS = 10;
const IMAGE_IFRAME_ATTACH_ERROR =
  'Image I-Frame player does not accept HTMLMediaElements';

type Constructor<T = object, A extends any[] = any[], Static = {}> = (new (
  ...a: A
) => T) &
  Static;

const loadMediaAtOptionsDefault: LoadMediaAtOptions = {
  seekOnAppend: true,
};
export interface HlsIFramesOnly extends Omit<
  Hls,
  | 'createIFramePlayer'
  | 'createImageIFramePlayer'
  | 'iframeVariants'
  | 'swapAudioCodec'
  | 'setAudioOption'
  | 'allAudioTracks'
  | 'audioTracks'
  | 'audioTrack'
  | 'nextAudioTrack'
  | 'setSubtitleOption'
  | 'allSubtitleTracks'
  | 'subtitleTracks'
  | 'subtitleTrack'
  | 'subtitleDisplay'
> {
  loadMediaAt(time: number, options?: Partial<LoadMediaAtOptions>): void;
}

export interface HlsImageIFramesOnly extends Omit<
  HlsIFramesOnly,
  | 'attachMedia'
  | 'detachMedia'
  | 'transferMedia'
  | 'recoverMediaError'
  | 'media'
> {
  loadMediaAt(time: number): void;
  attachImage(image: HTMLImageElement): void;
  detachImage(): void;
}

let HlsIFramesOnlyClass: ReturnType<typeof createHlsIFramesOnly>;
let HlsImageIFramesOnlyClass: ReturnType<typeof createHlsImageIFramesOnly>;

export class IFrameController extends Logger {
  private hls: Hls | undefined;

  // ManifestLoadedData forwarded to iframe instances
  private stats?: LoaderStats;
  private variableList: VariableMap | null = null;

  private initPTS: TimestampOffset[] = [];

  private iframeInstances: (HlsIFramesOnly | HlsImageIFramesOnly)[];
  private instanceCounter: number = 0;

  constructor(hls: Hls, HlsPlayerClass: typeof Hls) {
    super('iframes', hls.logger);
    HlsIFramesOnlyClass ||= createHlsIFramesOnly(HlsPlayerClass);
    HlsImageIFramesOnlyClass ||= createHlsImageIFramesOnly(HlsIFramesOnlyClass);
    this.hls = hls;
    this.iframeInstances = [];
    this.registerListeners();
  }

  private registerListeners() {
    const hls = this.hls;
    if (hls) {
      hls.on(Events.MANIFEST_LOADING, this.clearAsset, this);
      hls.on(Events.MANIFEST_LOADED, this.onManifestLoaded, this);
      hls.on(Events.LEVELS_UPDATED, this.onLevelsUpdated, this);
      hls.on(Events.INIT_PTS_FOUND, this.onInitPtsFound, this);
      hls.on(Events.FRAG_BUFFERED, this.onFragBuffered, this);
      hls.on(Events.DESTROYING, this.onDestroying, this);
    }
  }

  private unregisterListeners() {
    const hls = this.hls;
    if (hls) {
      hls.off(Events.MANIFEST_LOADING, this.clearAsset, this);
      hls.off(Events.MANIFEST_LOADED, this.onManifestLoaded, this);
      hls.off(Events.LEVELS_UPDATED, this.onLevelsUpdated, this);
      hls.off(Events.INIT_PTS_FOUND, this.onInitPtsFound, this);
      hls.off(Events.FRAG_BUFFERED, this.onFragBuffered, this);
      hls.off(Events.DESTROYING, this.onDestroying, this);
    }
  }

  private clearAsset() {
    this.stats = undefined;
    this.variableList = null;
    this.initPTS = [];
    this.iframeInstances.forEach((instance) => instance.destroy());
    this.iframeInstances.length = 0;
  }

  private onDestroying() {
    this.unregisterListeners();
    this.clearAsset();
    this.hls = undefined;
  }

  private onManifestLoaded(
    event: Events.MANIFEST_LOADED,
    data: ManifestLoadedData,
  ) {
    this.stats = data.stats;
    this.variableList = data.variableList;
  }

  private onLevelsUpdated(
    event: Events.LEVELS_UPDATED,
    { levels }: LevelsUpdatedData,
  ) {
    // Check for Pathway switch and priority change
    const pathwayPriority = this.hls?.pathwayPriority;
    if (levels.length && pathwayPriority) {
      this.iframeInstances.forEach((instance) => {
        instance.pathwayPriority = pathwayPriority;
      });
    }
  }

  private onInitPtsFound(
    event: Events.INIT_PTS_FOUND,
    { id, timestampOffsets }: InitPTSFoundData,
  ) {
    if (id === PlaylistLevelType.MAIN) {
      this.initPTS = timestampOffsets;
    }
  }

  private onFragBuffered(event: Events.FRAG_BUFFERED, data: FragBufferedData) {
    const hls = this.hls;
    if (!hls) {
      return;
    }
    if (
      hls.hasEnoughToStart &&
      (hls.mainForwardBufferInfo?.len || 0) >
        PRELOAD_IFRAME_PLAYLISTS_AFTER_BUFFER_SECONDS
    ) {
      this.iframeInstances.forEach((instance) => {
        if (!instance.loadingEnabled) {
          instance.startLoad(this.hls?.media?.currentTime || 0);
        }
      });
    }
  }

  public createIFramePlayer(
    configOverride?: Partial<HlsConfig> | undefined,
  ): HlsIFramesOnly | null {
    return this.createInstance(
      HlsIFramesOnlyClass,
      this.hls?.iframeVariants,
      configOverride,
    );
  }

  public createImageIFramePlayer(
    configOverride?: Partial<HlsConfig> | undefined,
  ): HlsImageIFramesOnly | null {
    const imageIframeVariants = this.hls?.iframeVariants.filter(
      (parsed) => parsed.imageCodec,
    );
    return this.createInstance(
      HlsImageIFramesOnlyClass,
      imageIframeVariants,
      configOverride,
      'image-',
    );
  }

  private createInstance<H extends HlsIFramesOnly | HlsImageIFramesOnly>(
    HlsIframeClass: Constructor<H>,
    iframeVariants: LevelParsed[] | undefined,
    configOverride: Partial<HlsConfig> | undefined,
    loggerLabelPrefix?: string,
  ): H | null {
    const { hls } = this;
    if (!hls) {
      return null;
    }
    const {
      url,
      userConfig,
      latestLevelDetails,
      loadLevelObj,
      loadLevel,
      bandwidthEstimate,
      sessionId,
    } = hls;
    const { stats, variableList } = this;
    if (!iframeVariants?.length || !stats || !url) {
      return null;
    }
    const loggerId = `${loggerLabelPrefix || ''}iframe-player-${this.instanceCounter++}`;
    const levels = hls.levels as (Level | undefined)[];
    const activeLevel = loadLevelObj || levels[loadLevel];
    const videoPreference = getVideoPreference(
      activeLevel,
      userConfig.videoPreference,
    );
    const pathwayId = activeLevel?.pathwayId || '.';

    // I-Frame player config specialized behavior for I-frame only streaming
    const playerConfig: Partial<HlsConfig> = {
      ...userConfig,
      loggerId,
      primarySessionId: sessionId,
      videoPreference,
      abrEwmaDefaultEstimate: bandwidthEstimate,
      // StreamController will be replaced in constructor (HlsIFramesOnlyClass | HlsImageIFramesOnlyClass)
      streamController: undefined,
      // Disable features not essential to streaming video I-Frames
      audioStreamController: undefined,
      audioTrackController: undefined,
      subtitleStreamController: undefined,
      subtitleTrackController: undefined,
      timelineController: undefined,
      id3TrackController: undefined,
      fpsController: undefined,
      gapController: undefined,
      iframeController: undefined,
      cmcd: undefined,
      // FIXME: Interstitials must not be loaded independently of parent player. Schedule should come from parent. (disabled for now)
      interstitialsController: undefined,

      // Only load and unload as needed
      backBufferLength: Infinity,
      maxMaxBufferLength: 1,
      // Adapt to attached HTMLVideoElement dimension
      capLevelToPlayerSize: true,

      // Streamline loading
      enableWorker: false,
      autoStartLoad: false,
      startFragPrefetch: false,
      testBandwidth: false,
      progressive: false,
      ...configOverride,
    };

    // Instance of HlsIFramesOnlyClass | HlsImageIFramesOnlyClass
    const iframeInstance = new HlsIframeClass(
      playerConfig,
      url,
      this.initPTS,
      latestLevelDetails,
    );

    // Remove destroyed instanced from list before adding new ones
    this.iframeInstances = this.iframeInstances.filter(
      (instance) => !instance.url,
    );
    this.iframeInstances.push(iframeInstance);

    iframeInstance.trigger(Events.MANIFEST_LOADED, {
      levels: iframeVariants,
      contentSteering: { uri: '', pathwayId },
      sessionKeys: null,
      audioTracks: [],
      iframeVariants: [],
      sessionData: null,
      startTimeOffset: null,
      stats,
      networkDetails: null,
      url,
      variableList,
    });

    return iframeInstance;
  }
}

function createHlsIFramesOnly(Base: Constructor<Hls>) {
  return class HlsIFramesOnly extends Base {
    constructor(
      playerConfig: Partial<HlsConfig>,
      url: string,
      initPTS: TimestampOffset[],
      latestLevelDetails: LevelDetails | null,
    ) {
      // Video I-Frame stream-controller load segments before seeking to them to render frames in desired order
      playerConfig.streamController ||= IFrameStreamController;
      super(playerConfig);

      // Hls.url matches the parent player session source url.
      // `Hls.url==null` is used in many places to determine if the instance was destroyed.
      this._url = url;

      // Align timestamps based on parent initPts (accounts for audio prime offset and parent variant decode time difference)
      (this.streamController as IFrameStreamController).setInitPts(initPTS);
      (this.streamController as IFrameStreamController).initDetails =
        latestLevelDetails;
    }

    loadSource() {}

    loadMediaAt(
      time: number,
      options: Partial<LoadMediaAtOptions> = loadMediaAtOptionsDefault,
    ) {
      if (time < 0) {
        return;
      }
      const settings = {
        ...loadMediaAtOptionsDefault,
        ...options,
      };
      if (!this.loadingEnabled) {
        this.startLoad(time);
      }
      (this.streamController as IFrameStreamController).loadMediaAt(
        time,
        settings,
      );
    }
  };
}

function createHlsImageIFramesOnly(Base: typeof HlsIFramesOnlyClass) {
  return class HlsImageIFramesOnly extends Base {
    constructor(
      playerConfig: Partial<HlsConfig>,
      url: string,
      initPTS: TimestampOffset[],
      latestLevelDetails: LevelDetails | null,
    ) {
      // Image I-Frame stream-controller does not use media element
      playerConfig.cmcdController = undefined;
      playerConfig.emeController = undefined;

      playerConfig.streamController ||= ImageIFrameStreamController;

      // Nice to have, need to replace `media` and attach/detach constraints
      playerConfig.capLevelController = undefined;

      // Omit BufferController since MSE is not involved in image processing
      playerConfig.bufferController = undefined;

      super(playerConfig, url, initPTS, latestLevelDetails);
    }

    attachImage(image: HTMLImageElement) {
      (this.streamController as ImageIFrameStreamController).image = image;
    }

    detachImage() {
      (this.streamController as ImageIFrameStreamController).image = undefined;
    }

    loadSource() {}

    attachMedia() {
      throw new Error(IMAGE_IFRAME_ATTACH_ERROR);
    }

    detachMedia() {}

    recoverMediaError() {}

    transferMedia() {
      return null;
    }

    loadMediaAt(time: number) {
      if (time < 0) {
        return null;
      }
      if (!this.loadingEnabled) {
        this.startLoad(time);
      }
      (this.streamController as ImageIFrameStreamController).loadMediaAt(time);
    }
  };
}
