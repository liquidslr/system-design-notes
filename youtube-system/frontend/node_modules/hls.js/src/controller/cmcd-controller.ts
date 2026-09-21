import {
  CMCD_HEADERS,
  CMCD_KEYS,
  CMCD_QUERY,
  CMCD_V1,
  CMCD_V1_KEYS,
  CMCD_V2,
  CmcdEventType,
  CmcdObjectType,
  CmcdPlayerState,
  CmcdReporter,
  CmcdStreamingFormat,
  CmcdStreamType,
  isCmcdCustomKey,
  toCmcdValue,
} from '@svta/cml-cmcd';
import { Events } from '../events';
import {
  addEventListener,
  removeEventListener,
} from '../utils/event-listener-helper';
import type {
  CmcdCustomReporter,
  FragmentLoaderConstructor,
  HlsConfig,
  PlaylistLoaderConstructor,
} from '../config';
import type Hls from '../hls';
import type { Fragment, MediaFragment, Part } from '../loader/fragment';
import type { ComponentAPI } from '../types/component-api';
import type {
  BufferAppendedData,
  BufferFlushedData,
  ErrorData,
  LevelSwitchedData,
  LevelSwitchingData,
  ManifestLoadingData,
  MediaAttachedData,
  MediaEndedData,
} from '../types/events';
import type { Level } from '../types/level';
import type {
  FragmentLoaderContext,
  Loader,
  LoaderCallbacks,
  LoaderConfiguration,
  LoaderContext,
  LoaderResponse,
  LoaderStats,
  PlaylistLoaderContext,
} from '../types/loader';
import type { Cmcd } from '@svta/cml-cmcd';

function validateCmcdCustomData(data: Record<string, unknown>): boolean {
  return Object.keys(data).every(isCmcdCustomKey);
}

/**
 * Controller to deal with Common Media Client Data (CMCD)
 * @see https://cdn.cta.tech/cta/media/media/resources/standards/pdfs/cta-5004-final.pdf
 */
export default class CMCDController implements ComponentAPI {
  private hls: Hls;
  private config: HlsConfig;
  private media?: HTMLMediaElement;
  private initialized: boolean = false;
  private starved: boolean = false;
  private buffering: boolean = true;
  private playerState?: CmcdPlayerState;
  private reporter?: CmcdReporter;
  private playheadLevel?: Level;

  constructor(hls: Hls) {
    this.hls = hls;
    const config = (this.config = hls.config);
    const { cmcd } = config;

    if (cmcd != null) {
      config.pLoader = this.createPlaylistLoader();
      config.fLoader = this.createFragmentLoader();

      this.registerListeners();
    }
  }

  private createReporter() {
    const { cmcd } = this.config;
    if (cmcd == null) {
      return;
    }

    const version = cmcd.version || CMCD_V1;

    this.reporter = new CmcdReporter(
      {
        sid: cmcd.sessionId || this.hls.sessionId,
        cid: cmcd.contentId,
        version,
        transmissionMode: cmcd.useHeaders === true ? CMCD_HEADERS : CMCD_QUERY,
        enabledKeys: cmcd.includeKeys ?? [
          ...(version >= CMCD_V2 ? CMCD_KEYS : CMCD_V1_KEYS),
        ],
        eventTargets: (cmcd.eventTargets ?? []).map(
          ({ includeKeys, ...rest }) => ({
            ...rest,
            enabledKeys: includeKeys ?? CMCD_KEYS,
          }),
        ),
      },
      cmcd.loader,
    );

    this.reporter.update({
      sf: CmcdStreamingFormat.HLS,
      sta: this.playerState,
    });

    if (cmcd.reporterCallback) {
      const reporter = this.reporter;
      const customKeyAndEventReport: CmcdCustomReporter = {
        updateCustomData: (data) => {
          if (validateCmcdCustomData(data)) {
            reporter.update(data);
          }
        },
        recordCustomEvent: (eventName, data = {}) => {
          if (validateCmcdCustomData(data)) {
            reporter.recordEvent(CmcdEventType.CUSTOM_EVENT, {
              cen: eventName,
              ...data,
            });
          }
        },
      };
      cmcd.reporterCallback(customKeyAndEventReport);
    }

    this.reporter.start();
  }

  private registerListeners() {
    const hls = this.hls;
    hls.on(Events.MANIFEST_LOADING, this.onManifestLoading, this);
    hls.on(Events.MEDIA_ATTACHING, this.onMediaAttaching, this);
    hls.on(Events.MEDIA_DETACHED, this.onMediaDetached, this);
    hls.on(Events.MEDIA_ENDED, this.onMediaEnded, this);
    hls.on(Events.ERROR, this.onError, this);
    hls.on(Events.LEVEL_SWITCHING, this.onLevelSwitching, this);
    hls.on(Events.LEVEL_SWITCHED, this.onLevelSwitched, this);
    hls.on(Events.BUFFER_APPENDED, this.onBufferInfoChange, this);
    hls.on(Events.BUFFER_FLUSHED, this.onBufferInfoChange, this);
  }

  private unregisterListeners() {
    const hls = this.hls;
    hls.off(Events.MANIFEST_LOADING, this.onManifestLoading, this);
    hls.off(Events.MEDIA_ATTACHING, this.onMediaAttaching, this);
    hls.off(Events.MEDIA_DETACHED, this.onMediaDetached, this);
    hls.off(Events.MEDIA_ENDED, this.onMediaEnded, this);
    hls.off(Events.ERROR, this.onError, this);
    hls.off(Events.LEVEL_SWITCHING, this.onLevelSwitching, this);
    hls.off(Events.LEVEL_SWITCHED, this.onLevelSwitched, this);
    hls.off(Events.BUFFER_APPENDED, this.onBufferInfoChange, this);
    hls.off(Events.BUFFER_FLUSHED, this.onBufferInfoChange, this);
  }

  destroy() {
    this.unregisterListeners();
    this.onMediaDetached();

    if (this.reporter) {
      this.reporter.stop(true);
      this.reporter = undefined;
    }

    // @ts-ignore
    this.hls = this.config = null;
    // @ts-ignore
    this.onWaiting = this.onPlay = this.onPlaying = this.onPause = null;
    // @ts-ignore
    this.onSeeking = this.onSeeked = this.onRateChange = this.media = null;
  }

  private onMediaAttaching(
    event: Events.MEDIA_ATTACHING,
    data: MediaAttachedData,
  ) {
    const media = (this.media = data.media);
    this.setPlayerState(
      this.media.autoplay
        ? CmcdPlayerState.STARTING
        : CmcdPlayerState.PRELOADING,
    );

    addEventListener(media, 'waiting', this.onWaiting);
    addEventListener(media, 'play', this.onPlay);
    addEventListener(media, 'playing', this.onPlaying);
    addEventListener(media, 'pause', this.onPause);
    addEventListener(media, 'seeking', this.onSeeking);
    addEventListener(media, 'seeked', this.onSeeked);
    addEventListener(media, 'ratechange', this.onRateChange);
  }

  private onMediaDetached() {
    const media = this.media;

    if (!media) {
      return;
    }

    removeEventListener(media, 'waiting', this.onWaiting);
    removeEventListener(media, 'play', this.onPlay);
    removeEventListener(media, 'playing', this.onPlaying);
    removeEventListener(media, 'pause', this.onPause);
    removeEventListener(media, 'seeking', this.onSeeking);
    removeEventListener(media, 'seeked', this.onSeeked);
    removeEventListener(media, 'ratechange', this.onRateChange);

    // @ts-ignore
    this.media = null;
  }

  private onWaiting = () => {
    if (this.initialized) {
      this.starved = true;
      this.setPlayerState(CmcdPlayerState.REBUFFERING);
    }

    this.buffering = true;
  };

  private onPlay = () => {
    if (!this.initialized) {
      this.setPlayerState(CmcdPlayerState.STARTING);
    }
  };

  private onPlaying = () => {
    if (!this.initialized) {
      this.initialized = true;
    }

    this.buffering = false;
    this.setPlayerState(CmcdPlayerState.PLAYING);
  };

  private onPause = () => {
    if (this.media && !this.media.ended) {
      this.setPlayerState(CmcdPlayerState.PAUSED);
    }
  };

  private onSeeking = () => {
    if (this.initialized) {
      this.setPlayerState(CmcdPlayerState.SEEKING);
    }
  };

  private onSeeked = () => {
    if (!this.initialized) {
      return;
    }
    if (this.media?.paused) {
      this.setPlayerState(CmcdPlayerState.PAUSED);
    }
  };

  private onRateChange = () => {
    if (this.reporter && this.media) {
      this.reporter.update({ pr: this.media.playbackRate });
    }
  };

  private onMediaEnded(event: Events.MEDIA_ENDED, data: MediaEndedData) {
    this.setPlayerState(CmcdPlayerState.ENDED);
  }

  private onManifestLoading(
    event: Events.MANIFEST_LOADING,
    data: ManifestLoadingData,
  ) {
    this.initialized = false;
    this.starved = false;
    this.buffering = true;

    if (this.reporter) {
      this.reporter.stop(true);
      this.reporter = undefined;
    }

    this.createReporter();

    if (!this.media) {
      this.setPlayerState(CmcdPlayerState.PRELOADING);
    }
  }

  private onError(event: Events.ERROR, data: ErrorData) {
    if (data.fatal) {
      this.setPlayerState(CmcdPlayerState.FATAL_ERROR);
      if (this.reporter) {
        this.reporter.recordEvent(CmcdEventType.ERROR, { ec: [data.details] });
      }
    }
  }

  private onLevelSwitching(
    event: Events.LEVEL_SWITCHING,
    data: LevelSwitchingData,
  ) {
    if (!this.reporter) {
      return;
    }

    const eventData: Cmcd = { br: [data.bitrate / 1000] };
    const frag = data.details?.fragments[0];
    if (frag) {
      eventData.ot = this.getObjectType(frag, data);
    }
    this.reporter.recordEvent(CmcdEventType.BITRATE_CHANGE, eventData);
  }

  private onLevelSwitched(
    _event: Events.LEVEL_SWITCHED,
    data: LevelSwitchedData,
  ) {
    const level = this.hls.levels[data.level];
    if (level) {
      this.playheadLevel = level;
    }
  }

  private setPlayerState(state: CmcdPlayerState) {
    this.playerState = state;
    if (this.reporter) {
      this.reporter.update({ sta: state });
    }
  }

  /**
   * Get the stream type based on level details.
   */
  private getStreamType(): CmcdStreamType | undefined {
    const details = this.hls.latestLevelDetails;

    if (!details) {
      return undefined;
    }

    if (!details.live) {
      return CmcdStreamType.VOD;
    }

    // TODO: Replace with an `isLowLatency` check in #7729
    if (!!details.partList && details.canBlockReload) {
      return CmcdStreamType.LOW_LATENCY;
    }

    return CmcdStreamType.LIVE;
  }

  /**
   * Apply CMCD data to a request using the reporter.
   */
  private apply(context: LoaderContext, data: Cmcd = {}) {
    if (!this.reporter) {
      return;
    }

    // Update persistent data
    this.reporter.update({
      mtp: [this.hls.bandwidthEstimate / 1000],
      pr: this.media?.playbackRate,
      st: this.getStreamType(),
    });

    const isVideo =
      data.ot === CmcdObjectType.INIT ||
      data.ot === CmcdObjectType.VIDEO ||
      data.ot === CmcdObjectType.MUXED;

    if (this.starved && isVideo) {
      data.bs = true;
      data.su = true;
      this.starved = false;
    }

    if (data.su == null) {
      data.su = this.buffering;
    }

    const report = this.reporter.createRequestReport(
      { url: context.url, headers: context.headers },
      data,
    );

    context.url = report.url;
    context.headers = report.headers;
  }

  /**
   * Apply CMCD data to a manifest request.
   */
  private applyPlaylistData = (context: PlaylistLoaderContext) => {
    try {
      this.apply(context, {
        ot: CmcdObjectType.MANIFEST,
        su: !this.initialized,
      });
    } catch (error) {
      this.hls.logger.warn('Could not generate manifest CMCD data.', error);
    }
  };

  /**
   * Apply CMCD data to a segment request
   */
  private applyFragmentData = (context: FragmentLoaderContext) => {
    try {
      const { frag, part } = context;
      const level = this.hls.levels[frag.level];
      const ot = this.getObjectType(frag, level);
      const data: Cmcd = { d: (part || frag).duration * 1000, ot };

      if (
        ot === CmcdObjectType.VIDEO ||
        ot === CmcdObjectType.AUDIO ||
        ot === CmcdObjectType.MUXED ||
        (ot == null && (frag.type === 'main' || frag.type === 'audio'))
      ) {
        const bitrateKbps = level.bitrate / 1000;
        data.br = [bitrateKbps];
        const { cmcd } = this.config;
        const rtpSafetyFactor = cmcd?.rtpSafetyFactor ?? 5;
        data.rtp = Math.round((bitrateKbps * rtpSafetyFactor) / 100) * 100;

        if (
          ot === CmcdObjectType.MUXED ||
          (ot == null && frag.type === 'main')
        ) {
          const tb = this.getTopBandwidth() / 1000;
          if (Number.isFinite(tb)) {
            data.tb = [tb];
          }

          const lb = this.getLowestBandwidth() / 1000;
          if (Number.isFinite(lb)) {
            data.lb = [lb];
          }
        }

        const bl = this.getBufferLength(frag);
        if (Number.isFinite(bl)) {
          data.bl = [bl];
          const pr = this.media?.playbackRate || 1;
          data.dl = Math.round(bl / pr / 100) * 100;
        }

        if (this.playheadLevel) {
          data.pb = [this.playheadLevel.bitrate / 1000];
        }

        const maxIdx = this.hls.maxAutoLevel;
        if (maxIdx >= 0) {
          const topLevel = this.hls.levels[maxIdx];
          if (topLevel) {
            data.tpb = [topLevel.bitrate / 1000];
          }
        }
      }

      const next = part ? this.getNextPart(part) : this.getNextFrag(frag);

      if (next?.url && next.url !== frag.url) {
        if (next.byteRange.length > 0) {
          data.nor = [
            toCmcdValue(next.url, {
              r: `${next.byteRange[0]}-${next.byteRange[1]}`,
            }),
          ];
        } else {
          data.nor = [next.url];
        }
      }

      this.apply(context, data);
    } catch (error) {
      this.hls.logger.warn('Could not generate segment CMCD data.', error);
    }
  };

  private getNextFrag(fragment: Fragment): Fragment | undefined {
    const levelDetails = this.hls.levels[fragment.level]?.details;
    if (levelDetails) {
      const index = (fragment.sn as number) - levelDetails.startSN;
      return levelDetails.fragments[index + 1];
    }

    return undefined;
  }

  private getNextPart(part: Part): Part | undefined {
    const { index, fragment } = part;
    const partList = this.hls.levels[fragment.level]?.details?.partList;

    if (partList) {
      const { sn } = fragment;
      for (let i = partList.length - 1; i >= 0; i--) {
        const p = partList[i];
        if (p.index === index && p.fragment.sn === sn) {
          return partList[i + 1];
        }
      }
    }

    return undefined;
  }

  /**
   * The CMCD object type.
   */
  private getObjectType(
    fragment: Fragment | MediaFragment,
    variant?: Level | LevelSwitchingData,
  ): CmcdObjectType | undefined {
    const { type } = fragment;

    if (type === 'subtitle') {
      return CmcdObjectType.TIMED_TEXT;
    }

    if (fragment.sn === 'initSegment') {
      return CmcdObjectType.INIT;
    }

    if (type === 'audio') {
      return CmcdObjectType.AUDIO;
    }

    if (type === 'main') {
      // Parsed elementary streams are ground truth when present.
      if (fragment.hasStreams) {
        const es = fragment.elementaryStreams;
        if (es.audiovideo) {
          return CmcdObjectType.MUXED;
        }
        if (es.video) {
          return CmcdObjectType.VIDEO;
        }
        if (es.audio) {
          return CmcdObjectType.AUDIO;
        }
      }
      // Fall back to variant codec info. STREAM-INF CODECS describes the variant
      // including any alternate renditions it pulls from, so audioCodec only
      // implies the main variant carries audio when no audio media options exist.
      if (variant) {
        const { audioCodec, videoCodec } = variant;
        if (!this.hls.audioTracks.length) {
          if (audioCodec && videoCodec) {
            return CmcdObjectType.MUXED;
          }
          if (audioCodec) {
            return CmcdObjectType.AUDIO;
          }
        }
        if (videoCodec) {
          return CmcdObjectType.VIDEO;
        }
      }
    }

    return undefined;
  }

  /**
   * Get the highest bitrate available for the source backing this fragment.
   * Audio renditions live in hls.audioTracks; everything else (including
   * audio-only main playlists) draws from hls.levels.
   */
  private getTopBandwidth() {
    let bitrate: number = 0;
    const hls = this.hls;
    const max = hls.maxAutoLevel;
    const len = max > -1 ? max + 1 : hls.levels.length;
    const levels = hls.levels.slice(0, len);

    levels.forEach((level) => {
      if (level.bitrate > bitrate) {
        bitrate = level.bitrate;
      }
    });

    return bitrate > 0 ? bitrate : NaN;
  }

  private getLowestBandwidth() {
    let bitrate: number = Infinity;
    const hls = this.hls;
    const max = hls.maxAutoLevel;
    const len = max > -1 ? max + 1 : hls.levels.length;
    const levels = hls.levels.slice(0, len);

    levels.forEach((level) => {
      if (level.bitrate < bitrate) {
        bitrate = level.bitrate;
      }
    });

    return Number.isFinite(bitrate) ? bitrate : NaN;
  }

  /**
   * Get the buffer length in milliseconds for the source backing this fragment.
   */
  private getBufferLength(fragment: Fragment | MediaFragment) {
    if (!this.media) {
      return NaN;
    }

    const info =
      fragment.type === 'audio'
        ? this.hls.audioForwardBufferInfo
        : this.hls.mainForwardBufferInfo;
    return info ? info.len * 1000 : NaN;
  }

  /**
   * Get the buffer length in milliseconds without a specific fragment context.
   * Used to keep `bl` fresh on event reports independent of segment requests.
   * Returns the playback bottleneck: min of main and audio forward buffer
   * lengths when both exist; otherwise whichever is available.
   */
  private getEventBufferLength(): number {
    if (!this.media) {
      return NaN;
    }
    const main = this.hls.mainForwardBufferInfo;
    const audio = this.hls.audioForwardBufferInfo;
    if (main && audio) {
      return Math.min(main.len, audio.len) * 1000;
    }
    const info = main || audio;
    return info ? info.len * 1000 : NaN;
  }

  private onBufferInfoChange(
    event: Events.BUFFER_APPENDED | Events.BUFFER_FLUSHED,
    data: BufferAppendedData | BufferFlushedData,
  ) {
    if (!this.reporter) {
      return;
    }
    const bl = this.getEventBufferLength();
    if (!Number.isFinite(bl)) {
      return;
    }
    this.reporter.update({ bl: [bl] });
  }

  private recordFragmentResponse = (
    url: string,
    response: LoaderResponse,
    stats: LoaderStats,
  ) => {
    const { cmcd } = this.config;
    const hasResponseTarget = cmcd?.eventTargets?.some((t) =>
      t.events?.includes(CmcdEventType.RESPONSE_RECEIVED),
    );
    if (!this.reporter || !(stats.loading.first > 0) || !hasResponseTarget) {
      return;
    }
    try {
      this.reporter.recordResponseReceived({
        request: { url },
        status: response.code,
        resourceTiming: {
          startTime: stats.loading.start,
          responseStart: stats.loading.first,
          duration: stats.loading.end - stats.loading.start,
          encodedBodySize: stats.total,
        },
      });
    } catch (error) {
      this.hls.logger.warn(
        'Could not record fragment response CMCD data.',
        error,
      );
    }
  };

  /**
   * Create a playlist loader
   */
  private createPlaylistLoader(): PlaylistLoaderConstructor | undefined {
    const { pLoader } = this.config;
    const apply = this.applyPlaylistData;
    const Ctor = pLoader || (this.config.loader as PlaylistLoaderConstructor);

    return class CmcdPlaylistLoader {
      private loader: Loader<PlaylistLoaderContext>;

      constructor(config: HlsConfig) {
        this.loader = new Ctor(config);
      }

      get stats() {
        return this.loader.stats;
      }

      get context() {
        return this.loader.context;
      }

      destroy() {
        this.loader.destroy();
      }

      abort() {
        this.loader.abort();
      }

      load(
        context: PlaylistLoaderContext,
        config: LoaderConfiguration,
        callbacks: LoaderCallbacks<PlaylistLoaderContext>,
      ) {
        apply(context);
        this.loader.load(context, config, callbacks);
      }
    };
  }

  /**
   * Create a fragment loader
   */
  private createFragmentLoader(): FragmentLoaderConstructor | undefined {
    const { fLoader } = this.config;
    const apply = this.applyFragmentData;
    const recordResponse = this.recordFragmentResponse;
    const Ctor = fLoader || (this.config.loader as FragmentLoaderConstructor);

    return class CmcdFragmentLoader {
      private loader: Loader<FragmentLoaderContext>;

      constructor(config: HlsConfig) {
        this.loader = new Ctor(config);
      }

      get stats() {
        return this.loader.stats;
      }

      get context() {
        return this.loader.context;
      }

      destroy() {
        this.loader.destroy();
      }

      abort() {
        this.loader.abort();
      }

      load(
        context: FragmentLoaderContext,
        config: LoaderConfiguration,
        callbacks: LoaderCallbacks<FragmentLoaderContext>,
      ) {
        apply(context);
        const { onSuccess } = callbacks;
        this.loader.load(context, config, {
          ...callbacks,
          onSuccess: (response, stats, ctx, networkDetails) => {
            onSuccess(response, stats, ctx, networkDetails);
            recordResponse(context.url, response, stats);
          },
        });
      }
    };
  }
}
