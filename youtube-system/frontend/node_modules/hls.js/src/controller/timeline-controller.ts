import { Events } from '../events';
import { PlaylistLevelType } from '../types/loader';
import Cea608Parser from '../utils/cea-608-parser';
import { IMSC1_CODEC, parseIMSC1 } from '../utils/imsc1-ttml-parser';
import { subtitleOptionsIdentical } from '../utils/media-option-attributes';
import { appendUint8Array } from '../utils/mp4-tools';
import OutputFilter from '../utils/output-filter';
import {
  addCueToTrack,
  createTrackNode,
  removeCuesInRange,
} from '../utils/texttrack-utils';
import { parseWebVTT } from '../utils/webvtt-parser';
import type { HlsConfig } from '../config';
import type Hls from '../hls';
import type { Fragment } from '../loader/fragment';
import type { ComponentAPI } from '../types/component-api';
import type {
  BufferAppendedData,
  BufferFlushingData,
  FragDecryptedData,
  FragLoadedData,
  FragLoadingData,
  FragParsingUserdataData,
  InitPTSFoundData,
  ManifestLoadedData,
  MediaAttachingData,
  MediaDetachingData,
  NonNativeTextTrack,
  SubtitleTracksUpdatedData,
} from '../types/events';
import type { MediaPlaylist } from '../types/media-playlist';
import type { VTTCCs } from '../types/vtt';
import type { CaptionScreen } from '../utils/cea-608-parser';
import type { CuesInterface } from '../utils/cues';
import type { TimestampOffset } from '../utils/timescale-conversion';

type TrackProperties = {
  label: string;
  languageCode: string;
  media?: MediaPlaylist;
};

export class TimelineController implements ComponentAPI {
  private hls: Hls;
  private media: HTMLMediaElement | null = null;
  private config: HlsConfig;
  private enabled: boolean = true;
  private Cues: CuesInterface;
  private tracks: Array<MediaPlaylist> = [];
  private initPTS: TimestampOffset[] = [];
  private unparsedVttFrags: Array<FragLoadedData | FragDecryptedData> = [];
  private captionsTracks: Record<string, HTMLTrackElement> = {};
  private cueCache: Record<string, VTTCue[]> = {};
  private nonNativeCaptionsTracks: Record<string, NonNativeTextTrack> = {};
  private cea608Parser1?: Cea608Parser;
  private cea608Parser2?: Cea608Parser;
  private lastCc: number = -1; // Last video (CEA-608) fragment CC
  private lastSn: number = -1; // Last video (CEA-608) fragment MSN
  private lastPartIndex: number = -1; // Last video (CEA-608) fragment Part Index
  private prevCC: number = -1; // Last subtitle fragment CC
  private vttCCs: VTTCCs = newVTTCCs();
  private captionsProperties: {
    textTrack1: TrackProperties;
    textTrack2: TrackProperties;
    textTrack3: TrackProperties;
    textTrack4: TrackProperties;
  };

  constructor(hls: Hls) {
    this.hls = hls;
    this.config = hls.config;
    this.Cues = hls.config.cueHandler;
    this.cueCache = {};

    this.captionsProperties = {
      textTrack1: {
        label: this.config.captionsTextTrack1Label,
        languageCode: this.config.captionsTextTrack1LanguageCode,
      },
      textTrack2: {
        label: this.config.captionsTextTrack2Label,
        languageCode: this.config.captionsTextTrack2LanguageCode,
      },
      textTrack3: {
        label: this.config.captionsTextTrack3Label,
        languageCode: this.config.captionsTextTrack3LanguageCode,
      },
      textTrack4: {
        label: this.config.captionsTextTrack4Label,
        languageCode: this.config.captionsTextTrack4LanguageCode,
      },
    };

    hls.on(Events.MEDIA_ATTACHING, this.onMediaAttaching, this);
    hls.on(Events.MEDIA_DETACHING, this.onMediaDetaching, this);
    hls.on(Events.MANIFEST_LOADING, this.onManifestLoading, this);
    hls.on(Events.MANIFEST_LOADED, this.onManifestLoaded, this);
    hls.on(Events.SUBTITLE_TRACKS_UPDATED, this.onSubtitleTracksUpdated, this);
    hls.on(Events.FRAG_LOADING, this.onFragLoading, this);
    hls.on(Events.FRAG_LOADED, this.onFragLoaded, this);
    hls.on(Events.FRAG_PARSING_USERDATA, this.onFragParsingUserdata, this);
    hls.on(Events.FRAG_DECRYPTED, this.onFragDecrypted, this);
    hls.on(Events.INIT_PTS_FOUND, this.onInitPtsFound, this);
    hls.on(Events.SUBTITLE_TRACKS_CLEARED, this.onSubtitleTracksCleared, this);
    hls.on(Events.BUFFER_APPENDED, this.onBufferAppended, this);
    hls.on(Events.BUFFER_FLUSHING, this.onBufferFlushing, this);
  }

  public destroy(): void {
    const { hls } = this;
    hls.off(Events.MEDIA_ATTACHING, this.onMediaAttaching, this);
    hls.off(Events.MEDIA_DETACHING, this.onMediaDetaching, this);
    hls.off(Events.MANIFEST_LOADING, this.onManifestLoading, this);
    hls.off(Events.MANIFEST_LOADED, this.onManifestLoaded, this);
    hls.off(Events.SUBTITLE_TRACKS_UPDATED, this.onSubtitleTracksUpdated, this);
    hls.off(Events.FRAG_LOADING, this.onFragLoading, this);
    hls.off(Events.FRAG_LOADED, this.onFragLoaded, this);
    hls.off(Events.FRAG_PARSING_USERDATA, this.onFragParsingUserdata, this);
    hls.off(Events.FRAG_DECRYPTED, this.onFragDecrypted, this);
    hls.off(Events.INIT_PTS_FOUND, this.onInitPtsFound, this);
    hls.off(Events.SUBTITLE_TRACKS_CLEARED, this.onSubtitleTracksCleared, this);
    hls.off(Events.BUFFER_APPENDED, this.onBufferAppended, this);
    hls.off(Events.BUFFER_FLUSHING, this.onBufferFlushing, this);
    // @ts-ignore
    this.hls = this.config = this.media = null;
    this.cea608Parser1 = this.cea608Parser2 = undefined;
  }

  private initCea608Parsers() {
    const channel1 = new OutputFilter(this, 'textTrack1');
    const channel2 = new OutputFilter(this, 'textTrack2');
    const channel3 = new OutputFilter(this, 'textTrack3');
    const channel4 = new OutputFilter(this, 'textTrack4');
    this.cea608Parser1 = new Cea608Parser(1, channel1, channel2);
    this.cea608Parser2 = new Cea608Parser(3, channel3, channel4);
  }

  public addCues(
    trackName: string,
    startTime: number,
    endTime: number,
    screen: CaptionScreen,
    cueRanges: Array<[number, number]>,
  ) {
    // skip cues which overlap more than 50% with previously parsed time ranges
    let merged = false;
    for (let i = cueRanges.length; i--; ) {
      const cueRange = cueRanges[i];
      const overlap = intersection(
        cueRange[0],
        cueRange[1],
        startTime,
        endTime,
      );
      if (overlap >= 0) {
        cueRange[0] = Math.min(cueRange[0], startTime);
        cueRange[1] = Math.max(cueRange[1], endTime);
        merged = true;
        if (overlap / (endTime - startTime) > 0.5) {
          return;
        }
      }
    }
    if (!merged) {
      cueRanges.push([startTime, endTime]);
    }

    if (this.config.renderTextTracksNatively) {
      const cache = this.cueCache[trackName];
      if (cache) {
        const cues = this.Cues.newCue(null, startTime, endTime, screen);
        if (cues.length) {
          cache.push.apply(cache, cues);
        }
      } else {
        const track = this.captionsTracks[trackName].track;
        this.Cues.newCue(track, startTime, endTime, screen);
      }
    } else {
      const cues = this.Cues.newCue(null, startTime, endTime, screen);
      const closedCaptions = this.captionsProperties[trackName]?.media;
      this.hls.trigger(Events.CUES_PARSED, {
        type: 'captions',
        cues,
        track: trackName,
        closedCaptions,
      });
    }
  }

  // Triggered when an initial PTS is found; used for synchronisation of WebVTT.
  private onInitPtsFound(
    event: Events.INIT_PTS_FOUND,
    { id, timestampOffsets }: InitPTSFoundData,
  ) {
    const { unparsedVttFrags } = this;
    if (id === PlaylistLevelType.MAIN) {
      this.initPTS = timestampOffsets;
    }

    // Due to asynchronous processing, initial PTS may arrive later than the first VTT fragments are loaded.
    // Parse any unparsed fragments upon receiving the initial PTS.
    if (unparsedVttFrags.length) {
      this.unparsedVttFrags = [];
      unparsedVttFrags.forEach((data) => {
        if (this.initPTS[data.frag.cc]) {
          this.onFragLoaded(Events.FRAG_LOADED, data as FragLoadedData);
        } else {
          this.hls.trigger(Events.SUBTITLE_FRAG_PROCESSED, {
            success: false,
            frag: data.frag,
            part: null,
            error: new Error(
              'Subtitle discontinuity domain does not match main',
            ),
          });
        }
      });
    }
  }

  public createCaptionsTrack(trackName: string) {
    if (this.config.renderTextTracksNatively) {
      this.createNativeTrack(trackName);
    } else {
      this.createNonNativeTrack(trackName);
    }
  }

  private createNativeTrack(trackName: string) {
    if (this.captionsTracks[trackName]) {
      return;
    }
    const { captionsProperties, captionsTracks, cueCache, media } = this;
    const { label, languageCode } = captionsProperties[trackName];
    if (media) {
      cueCache[trackName] = [];
      captionsTracks[trackName] = createTrackNode(
        media,
        'captions',
        label,
        languageCode,
        'hidden',
      );
    }
  }

  private createNonNativeTrack(trackName: string) {
    if (this.nonNativeCaptionsTracks[trackName]) {
      return;
    }
    // Create a list of a single track for the provider to consume
    const trackProperties: TrackProperties = this.captionsProperties[trackName];
    if (!trackProperties) {
      return;
    }
    const label = trackProperties.label as string;
    const track = {
      _id: trackName,
      label,
      kind: 'captions',
      default: trackProperties.media ? !!trackProperties.media.default : false,
      closedCaptions: trackProperties.media,
    };
    this.nonNativeCaptionsTracks[trackName] = track;
    this.hls.trigger(Events.NON_NATIVE_TEXT_TRACKS_FOUND, { tracks: [track] });
  }

  private onMediaAttaching(
    event: Events.MEDIA_ATTACHING,
    data: MediaAttachingData,
  ) {
    this.media = data.media;
  }

  private onMediaDetaching(
    event: Events.MEDIA_DETACHING,
    data: MediaDetachingData,
  ) {
    const transferringMedia = !!data.transferMedia;
    this.media = null;
    if (transferringMedia) {
      return;
    }

    if (this.config.renderTextTracksNatively) {
      const { captionsTracks, cueCache } = this;
      for (const trackName in captionsTracks) {
        captionsTracks[trackName].remove();
        delete cueCache[trackName];
      }
    }
    this.cueCache = {};
    this.captionsTracks = {};
    this.nonNativeCaptionsTracks = {};
  }

  private onManifestLoading() {
    // Detect discontinuity in video fragment (CEA-608) parsing
    this.lastCc = -1;
    this.lastSn = -1;
    this.lastPartIndex = -1;
    // Detect discontinuity in subtitle manifests
    this.prevCC = -1;
    this.vttCCs = newVTTCCs();
    this.tracks = [];
    this.captionsTracks = {};
    this.nonNativeCaptionsTracks = {};
    this.unparsedVttFrags = [];
    this.initPTS = [];
    if (this.cea608Parser1 && this.cea608Parser2) {
      this.cea608Parser1.reset();
      this.cea608Parser2.reset();
    }
  }

  private onSubtitleTracksUpdated(
    event: Events.SUBTITLE_TRACKS_UPDATED,
    data: SubtitleTracksUpdatedData,
  ) {
    const tracks: Array<MediaPlaylist> = data.subtitleTracks || [];
    if (
      tracks.length &&
      !this.config.renderTextTracksNatively &&
      !subtitleOptionsIdentical(this.tracks, tracks)
    ) {
      // Create a list of tracks for the provider to consume
      const tracksList = tracks.map((track) => {
        return {
          label: track.name,
          kind: track.type.toLowerCase(),
          default: track.default,
          subtitleTrack: track,
        };
      });
      this.hls.trigger(Events.NON_NATIVE_TEXT_TRACKS_FOUND, {
        tracks: tracksList,
      });
    }
    this.tracks = tracks;
  }

  private onManifestLoaded(
    event: Events.MANIFEST_LOADED,
    data: ManifestLoadedData,
  ) {
    if (this.config.enableCEA708Captions && data.captions) {
      data.captions.forEach((captionsTrack) => {
        const instreamIdMatch = /(?:CC|SERVICE)([1-4])/.exec(
          captionsTrack.instreamId as string,
        );
        if (!instreamIdMatch) {
          return;
        }
        const trackName = `textTrack${instreamIdMatch[1]}`;
        const trackProperties: TrackProperties =
          this.captionsProperties[trackName];
        if (!trackProperties) {
          return;
        }
        trackProperties.label = captionsTrack.name;
        if (captionsTrack.lang) {
          // optional attribute
          trackProperties.languageCode = captionsTrack.lang;
        }
        trackProperties.media = captionsTrack;
      });
    }
  }

  private closedCaptionsForLevel(frag: Fragment): string | undefined {
    const level = this.hls.levels[frag.level];
    return level?.attrs['CLOSED-CAPTIONS'];
  }

  private onFragLoading(event: Events.FRAG_LOADING, data: FragLoadingData) {
    // if this frag isn't contiguous, clear the parser so cues with bad start/end times aren't added to the textTrack
    if (this.enabled && data.frag.type === PlaylistLevelType.MAIN) {
      const { cea608Parser1, cea608Parser2, lastSn } = this;
      const { cc, sn } = data.frag;
      const partIndex = data.part?.index ?? -1;
      if (cea608Parser1 && cea608Parser2) {
        if (
          sn !== lastSn + 1 ||
          (sn === lastSn && partIndex !== this.lastPartIndex + 1) ||
          cc !== this.lastCc
        ) {
          cea608Parser1.reset();
          cea608Parser2.reset();
        }
      }
      this.lastCc = cc as number;
      this.lastSn = sn as number;
      this.lastPartIndex = partIndex;
    }
  }

  private onFragLoaded(
    event: Events.FRAG_LOADED,
    data: FragDecryptedData | FragLoadedData,
  ) {
    const { frag, payload } = data;
    if (
      frag.level < this.tracks.length &&
      frag.type === PlaylistLevelType.SUBTITLE
    ) {
      // If fragment is subtitle type, parse as WebVTT.
      // An empty payload is valid when an init segment supplies the WebVTT header.
      if (payload.byteLength || frag.initSegment?.data?.byteLength) {
        const decryptData = frag.decryptdata;
        // fragment after decryption has a stats object
        const decrypted = 'stats' in data;
        // If the subtitles are not encrypted, parse VTTs now. Otherwise, we need to wait.
        if (decryptData == null || !decryptData.encrypted || decrypted) {
          const trackPlaylistMedia = this.tracks[frag.level] as
            | MediaPlaylist
            | undefined;
          const vttCCs = this.vttCCs;
          if (!vttCCs[frag.cc]) {
            vttCCs[frag.cc] = {
              start: frag.start,
              prevCC: this.prevCC,
              new: true,
            };
            this.prevCC = frag.cc;
          }
          if (trackPlaylistMedia?.textCodec === IMSC1_CODEC) {
            this._parseIMSC1(data);
          } else {
            this._parseVTTs(data);
          }
        }
      } else {
        // In case there is no payload, finish unsuccessfully.
        const part = 'part' in data ? data.part : null;
        this.hls.trigger(Events.SUBTITLE_FRAG_PROCESSED, {
          success: false,
          frag,
          part,
          error: new Error('Empty subtitle payload'),
        });
      }
    }
  }

  private _parseIMSC1(data: FragDecryptedData | FragLoadedData) {
    const { frag, payload } = data;
    const part = 'part' in data ? data.part : null;
    const hls = this.hls;
    parseIMSC1(
      payload,
      this.initPTS[frag.cc],
      (cues) => {
        this._appendCues(cues, frag.level);
        hls.trigger(Events.SUBTITLE_FRAG_PROCESSED, {
          success: true,
          frag,
          part,
        });
      },
      (error) => {
        hls.logger.log(
          `Cannot parse IMSC1 (sn: ${frag.sn} @${frag.start}): ${error}`,
        );
        hls.trigger(Events.SUBTITLE_FRAG_PROCESSED, {
          success: false,
          frag,
          part,
          error,
        });
      },
    );
  }

  private _parseVTTs(data: FragDecryptedData | FragLoadedData) {
    const { frag, payload } = data;
    const part = 'part' in data ? data.part : null;
    // We need an initial synchronisation PTS. Store fragments as long as none has arrived
    const { initPTS, unparsedVttFrags } = this;
    const maxAvCC = initPTS.length - 1;
    if (!initPTS[frag.cc] && maxAvCC === -1) {
      unparsedVttFrags.push(data);
      return;
    }

    const hls = this.hls;
    // Parse the WebVTT file contents.
    const vttHeader = frag.initSegment?.data;
    const payloadWebVTT = vttHeader
      ? appendUint8Array(vttHeader, new Uint8Array(payload)).buffer
      : payload;
    parseWebVTT(
      payloadWebVTT,
      this.initPTS[frag.cc],
      this.vttCCs,
      frag.cc,
      (part && !vttHeader ? part : frag).start,
      (cues) => {
        this._appendCues(cues, frag.level);
        hls.trigger(Events.SUBTITLE_FRAG_PROCESSED, {
          success: true,
          frag,
          part,
        });
      },
      (error) => {
        const missingInitPTS = error.message.startsWith('Missing initPTS');
        hls.logger.log(
          `${missingInitPTS ? 'Deferred parsing of' : 'Cannot parse'} VTT cue (sn: ${frag.sn} @${frag.start}): ${error}`,
        );
        if (missingInitPTS) {
          unparsedVttFrags.push(data);
          return;
        } else if (this.config.enableIMSC1) {
          this._fallbackToIMSC1(data);
        }
        // Something went wrong while parsing. Trigger event with success false.
        hls.trigger(Events.SUBTITLE_FRAG_PROCESSED, {
          success: false,
          frag,
          part,
          error,
        });
      },
    );
  }

  private _fallbackToIMSC1(data: FragDecryptedData | FragLoadedData) {
    const { frag, payload } = data;
    // If textCodec is unknown, try parsing as IMSC1. Set textCodec based on the result
    const trackPlaylistMedia = this.tracks[frag.level];
    if (!trackPlaylistMedia.textCodec) {
      parseIMSC1(
        payload,
        this.initPTS[frag.cc],
        () => {
          trackPlaylistMedia.textCodec = IMSC1_CODEC;
          this._parseIMSC1(data);
        },
        () => {
          trackPlaylistMedia.textCodec = 'wvtt';
        },
      );
    }
  }

  private _appendCues(cues: VTTCue[], fragLevel: number) {
    const hls = this.hls;
    if (this.config.renderTextTracksNatively) {
      const textTrack = this.tracks[fragLevel].trackNode?.track;
      // WebVTTParser.parse is an async method and if the currently selected text track mode is set to "disabled"
      // before parsing is done then don't try to access currentTrack.cues.getCueById as cues will be null
      // and trying to access getCueById method of cues will throw an exception
      // Because we check if the mode is disabled, we can force check `cues` below. They can't be null.
      if (!textTrack || textTrack.mode === 'disabled') {
        return;
      }
      cues.forEach((cue) => addCueToTrack(textTrack, cue));
    } else {
      const currentTrack = this.tracks[fragLevel];
      if (!currentTrack) {
        return;
      }
      const track = currentTrack.default ? 'default' : 'subtitles' + fragLevel;
      hls.trigger(Events.CUES_PARSED, {
        type: 'subtitles',
        cues,
        track,
        subtitleTrack: currentTrack,
      });
    }
  }

  private onFragDecrypted(
    event: Events.FRAG_DECRYPTED,
    data: FragDecryptedData,
  ) {
    const { frag } = data;
    if (frag.type === PlaylistLevelType.SUBTITLE) {
      this.onFragLoaded(Events.FRAG_LOADED, data as unknown as FragLoadedData);
    }
  }

  private onSubtitleTracksCleared() {
    this.tracks = [];
    this.captionsTracks = {};
  }

  private onFragParsingUserdata(
    event: Events.FRAG_PARSING_USERDATA,
    data: FragParsingUserdataData,
  ) {
    if (!this.enabled || !this.config.enableCEA708Captions) {
      return;
    }
    const { frag, samples } = data;
    if (
      frag.type === PlaylistLevelType.MAIN &&
      this.closedCaptionsForLevel(frag) === 'NONE'
    ) {
      return;
    }
    // If the event contains captions (found in the bytes property), push all bytes into the parser immediately
    // It will create the proper timestamps based on the PTS value
    for (let i = 0; i < samples.length; i++) {
      const ccBytes = samples[i].bytes;
      if (ccBytes) {
        if (!this.cea608Parser1) {
          this.initCea608Parsers();
        }
        const ccdatas = this.extractCea608Data(ccBytes);
        this.cea608Parser1!.addData(samples[i].pts, ccdatas[0]);
        this.cea608Parser2!.addData(samples[i].pts, ccdatas[1]);
      }
    }
  }

  private onBufferAppended(
    event: Events.BUFFER_APPENDED,
    data: BufferAppendedData,
  ) {
    if (this.config.renderTextTracksNatively) {
      const { type, timeRanges } = data;
      if (type === 'video' && timeRanges[type]?.length) {
        const { captionsTracks, cueCache } = this;
        Object.keys(cueCache).forEach((trackName) => {
          const track = captionsTracks[trackName]?.track;
          if (track) {
            const cues = cueCache[trackName];
            for (let i = 0; i < cues.length; i++) {
              addCueToTrack(track, cues[i]);
            }
          }
          delete cueCache[trackName];
        });
      }
    }
  }

  onBufferFlushing(event: Events.BUFFER_FLUSHING, data: BufferFlushingData) {
    const { startOffset, endOffset, endOffsetSubtitles, type } = data;
    const { media } = this;
    if (!media || media.currentTime < endOffset) {
      return;
    }
    // Clear 608 caption cues from the captions TextTracks when the video back buffer is flushed
    // Forward cues are never removed because we can loose streamed 608 content from recent fragments
    if (!type || type === 'video') {
      const { captionsTracks, cueCache } = this;
      Object.keys(captionsTracks).forEach((trackName) =>
        removeCuesInRange(
          captionsTracks[trackName].track,
          startOffset,
          endOffset,
        ),
      );
      Object.keys(cueCache).forEach((trackName) => {
        const cues = cueCache[trackName];
        for (let i = cues.length; i--; ) {
          const cue = cues[i];
          if (cue.startTime >= startOffset && cue.endTime <= endOffset) {
            cues.splice(i, 1);
          }
        }
      });
    }
    if (this.config.renderTextTracksNatively) {
      // Clear VTT/IMSC1 subtitle cues from the subtitle TextTracks when the back buffer is flushed
      if (startOffset === 0 && endOffsetSubtitles !== undefined) {
        this.tracks.forEach((track) => {
          const textTrack = track.trackNode?.track;
          if (textTrack) {
            removeCuesInRange(textTrack, startOffset, endOffsetSubtitles);
          }
        });
      }
    }
  }

  private extractCea608Data(byteArray: Uint8Array): number[][] {
    const actualCCBytes: number[][] = [[], []];
    const count = byteArray[0] & 0x1f;
    let position = 2;

    for (let j = 0; j < count; j++) {
      const tmpByte = byteArray[position++];
      const ccbyte1 = 0x7f & byteArray[position++];
      const ccbyte2 = 0x7f & byteArray[position++];
      if (ccbyte1 === 0 && ccbyte2 === 0) {
        continue;
      }
      const ccValid = (0x04 & tmpByte) !== 0; // Support all four channels
      if (ccValid) {
        const ccType = 0x03 & tmpByte;
        if (
          0x00 /* CEA608 field1*/ === ccType ||
          0x01 /* CEA608 field2*/ === ccType
        ) {
          // Exclude CEA708 CC data.
          actualCCBytes[ccType].push(ccbyte1);
          actualCCBytes[ccType].push(ccbyte2);
        }
      }
    }
    return actualCCBytes;
  }
}

function intersection(x1: number, x2: number, y1: number, y2: number): number {
  return Math.min(x2, y2) - Math.max(x1, y1);
}

function newVTTCCs(): VTTCCs {
  return {
    ccOffset: 0,
    presentationOffset: 0,
    0: {
      start: 0,
      prevCC: -1,
      new: true,
    },
  };
}
