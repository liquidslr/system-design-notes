import type {
  AttachMediaSourceData,
  BaseTrackSet,
  BufferCreatedTrackSet,
  MediaOverrides,
  ParsedTrack,
  SourceBufferName,
  SourceBufferTrackSet,
} from './buffer';
import type { MetadataSample, UserdataSample } from './demuxer';
import type {
  HdcpLevel,
  HlsUrlParameters,
  Level,
  LevelAttributes,
  LevelParsed,
  VariableMap,
} from './level';
import type {
  Loader,
  LoaderContext,
  LoaderResponse,
  LoaderStats,
  PlaylistLevelType,
  PlaylistLoaderContext,
} from './loader';
import type { MediaPlaylist, MediaPlaylistType } from './media-playlist';
import type { ChunkMetadata } from './transmuxer';
import type { SteeringManifest } from '../controller/content-steering-controller';
import type { IErrorAction } from '../controller/error-controller';
import type { HlsAssetPlayer } from '../controller/interstitial-player';
import type {
  InterstitialScheduleDurations,
  InterstitialScheduleItem,
} from '../controller/interstitials-schedule';
import type { ErrorDetails, ErrorTypes } from '../errors';
import type { HlsListeners } from '../events';
import type { NullableNetworkDetails } from './network-details';
import type { Fragment, MediaFragment, Part } from '../loader/fragment';
import type {
  AssetListJSON,
  InterstitialAssetItem,
  InterstitialEvent,
  InterstitialEventWithAssetList,
} from '../loader/interstitial-event';
import type { KeyLoaderInfo } from '../loader/key-loader';
import type { LevelDetails } from '../loader/level-details';
import type { LevelKey } from '../loader/level-key';
import type { LoadStats } from '../loader/load-stats';
import type { AttrList } from '../utils/attr-list';
import type { BufferInfo } from '../utils/buffer-helper';
import type { TimestampOffset } from '../utils/timescale-conversion';

export interface MediaAttachingData {
  media: HTMLMediaElement;
  mediaSource?: MediaSource | null;
  tracks?: SourceBufferTrackSet;
  overrides?: MediaOverrides;
}

export interface MediaAttachedData {
  media: HTMLMediaElement;
  mediaSource?: MediaSource;
}

export interface MediaDetachingData {
  transferMedia?: AttachMediaSourceData | null;
}

export interface MediaDetachedData {
  transferMedia?: AttachMediaSourceData | null;
}

export interface MediaEndedData {
  stalled: boolean;
}

export interface BufferCodecsData {
  video?: ParsedTrack;
  audio?: ParsedTrack;
  audiovideo?: ParsedTrack;
  tracks?: BaseTrackSet;
}

export interface BufferCreatedData {
  tracks: BufferCreatedTrackSet;
}

export interface BufferAppendingData {
  type: SourceBufferName;
  frag: Fragment;
  part: Part | null;
  chunkMeta: ChunkMetadata;
  offset?: number | undefined;
  parent: PlaylistLevelType;
  data: Uint8Array<ArrayBuffer>;
}

export interface BufferAppendedData {
  type: SourceBufferName;
  frag: Fragment;
  part: Part | null;
  chunkMeta: ChunkMetadata;
  parent: PlaylistLevelType;
  timeRanges: Partial<Record<SourceBufferName, TimeRanges>>;
}

export interface BufferEOSData {
  type: SourceBufferName | null;
}

export interface BufferFlushingData {
  startOffset: number;
  endOffset: number;
  endOffsetSubtitles?: number;
  type: SourceBufferName | null;
}

export interface BufferFlushedData {
  type: SourceBufferName;
  start: number;
  end: number;
  error?: Error;
}

export interface ManifestLoadingData {
  url: string;
}

export type ContentSteeringOptions = {
  uri: string;
  pathwayId: string;
};

export interface ManifestLoadedData {
  audioTracks: MediaPlaylist[];
  captions?: MediaPlaylist[];
  contentSteering: ContentSteeringOptions | null;
  iframeVariants: LevelParsed[];
  levels: LevelParsed[];
  networkDetails: NullableNetworkDetails;
  sessionData: Record<string, AttrList> | null;
  sessionKeys: LevelKey[] | null;
  startTimeOffset: number | null;
  stats: LoaderStats;
  subtitles?: MediaPlaylist[];
  url: string;
  variableList: VariableMap | null;
}

export interface ManifestParsedData {
  levels: Level[];
  audioTracks: MediaPlaylist[];
  subtitleTracks: MediaPlaylist[];
  iframeVariants: LevelParsed[];
  sessionData: Record<string, AttrList> | null;
  sessionKeys: LevelKey[] | null;
  firstLevel: number;
  stats: LoaderStats;
  audio: boolean;
  video: boolean;
  altAudio: boolean;
}

export interface LevelSwitchingData {
  level: number;
  attrs: LevelAttributes;
  details: LevelDetails | undefined;
  bitrate: number;
  averageBitrate: number;
  maxBitrate: number;
  realBitrate: number;
  width: number;
  height: number;
  codecSet: string;
  audioCodec: string | undefined;
  videoCodec: string | undefined;
  audioGroups: (string | undefined)[] | undefined;
  subtitleGroups: (string | undefined)[] | undefined;
  loaded: { bytes: number; duration: number } | undefined;
  loadError: number;
  fragmentError: number;
  name: string | undefined;
  id: number;
  uri: string;
  // Deprecated (retained for backwards compatibility)
  url: string[];
  urlId: 0;
  audioGroupIds: (string | undefined)[] | undefined;
  textGroupIds: (string | undefined)[] | undefined;
}

export interface LevelSwitchedData {
  level: number;
}

export interface TrackLoadingData {
  id: number;
  groupId: string;
  track: MediaPlaylist;
  url: string;
  deliveryDirectives: HlsUrlParameters | null;
}

export interface LevelLoadingData {
  id: number;
  level: number;
  levelInfo: Level;
  pathwayId: string | undefined;
  url: string;
  deliveryDirectives: HlsUrlParameters | null;
}

export interface TrackLoadedData {
  details: LevelDetails;
  id: number;
  groupId: string;
  networkDetails: NullableNetworkDetails;
  stats: LoaderStats;
  deliveryDirectives: HlsUrlParameters | null;
  track: MediaPlaylist;
  context?: PlaylistLoaderContext;
}

export interface LevelLoadedData {
  details: LevelDetails;
  id: number;
  level: number;
  levelInfo: Level;
  networkDetails: NullableNetworkDetails;
  stats: LoaderStats;
  deliveryDirectives: HlsUrlParameters | null;
  withoutMultiVariant?: boolean;
  context?: PlaylistLoaderContext;
}

export interface LevelUpdatedData {
  details: LevelDetails;
  level: number;
}

export interface AudioTrackUpdatedData {
  details: LevelDetails;
  id: number;
  groupId: string;
}

export interface SubtitleTrackUpdatedData {
  details: LevelDetails;
  id: number;
  groupId: string;
}

export interface LevelPTSUpdatedData {
  details: LevelDetails;
  level: Level;
  drift: number;
  type: string;
  frag: Fragment;
  start: number;
  end: number;
}

export interface AudioTrackSwitchingData extends MediaPlaylist {
  flushImmediate?: boolean;
}

export interface AudioTrackSwitchedData extends MediaPlaylist {}

export interface AudioTrackLoadedData extends TrackLoadedData {}

export interface AudioTracksUpdatedData {
  audioTracks: MediaPlaylist[];
}

export interface SubtitleTracksUpdatedData {
  subtitleTracks: MediaPlaylist[];
}

export interface SubtitleTrackSwitchData {
  id: number;
  name?: string;
  groupId?: string;
  type?: MediaPlaylistType | 'main';
  url?: string;
}

export interface SubtitleTrackLoadedData extends TrackLoadedData {}

export interface TrackSwitchedData {
  id: number;
}

export interface SubtitleFragProcessed {
  success: boolean;
  frag: Fragment;
  part: Part | null;
}

export interface FragChangedData {
  frag: MediaFragment;
  previousFrag: MediaFragment | null;
}

export interface FPSDropData {
  currentDropped: number;
  currentDecoded: number;
  totalDroppedFrames: number;
}

export interface FPSDropLevelCappingData {
  droppedLevel: number;
  level: number;
}

export interface MaxAutoLevelUpdatedData {
  autoLevelCapping: number;
  levels: Level[] | null;
  maxAutoLevel: number;
  minAutoLevel: number;
  maxHdcpLevel: HdcpLevel;
}

export interface ErrorData {
  type: ErrorTypes;
  details: ErrorDetails;
  error: Error;
  fatal: boolean;
  appendsWithoutProgress?: number;
  errorAction?: IErrorAction;
  buffer?: number;
  bufferInfo?: BufferInfo;
  bytes?: number;
  chunkMeta?: ChunkMetadata;
  context?: PlaylistLoaderContext;
  decryptdata?: LevelKey;
  event?: keyof HlsListeners | 'demuxerWorker';
  frag?: Fragment;
  part?: Part | null;
  level?: number | undefined;
  levelRetry?: boolean;
  loader?: Loader<LoaderContext>;
  networkDetails?: NullableNetworkDetails;
  stalled?: { start: number };
  stats?: LoaderStats;
  mimeType?: string;
  reason?: string;
  response?: LoaderResponse;
  url?: string;
  parent?: PlaylistLevelType;
  sourceBufferName?: SourceBufferName;
  interstitial?: InterstitialEvent;
  /**
   * @deprecated Use ErrorData.error
   */
  err?: {
    // comes from transmuxer interface
    message: string;
  };
}

export interface SubtitleFragProcessedData {
  success: boolean;
  frag: Fragment;
  part: Part | null;
  error?: Error;
}

export interface CuesParsedData {
  type: 'captions' | 'subtitles';
  cues: any;
  track: string;
  closedCaptions?: MediaPlaylist | undefined;
  subtitleTrack?: MediaPlaylist;
}

export type NonNativeTextTrack = {
  _id?: string;
  label: string;
  kind: string;
  default: boolean;
  closedCaptions?: MediaPlaylist;
  subtitleTrack?: MediaPlaylist;
};

export interface NonNativeTextTracksData {
  tracks: Array<NonNativeTextTrack>;
}

export interface InitPTSFoundData {
  timestampOffsets: TimestampOffset[];
  id: PlaylistLevelType;
  frag: MediaFragment;
  initPTS: number;
  timescale: number;
  trackId: number;
}

export interface FragLoadingData {
  frag: Fragment;
  part?: Part;
  targetBufferTime: number | null;
}

export interface FragLoadEmergencyAbortedData {
  frag: Fragment;
  part: Part | null;
  stats: LoaderStats;
}

export interface FragLoadedData {
  frag: Fragment;
  part: Part | null;
  payload: ArrayBuffer;
  networkDetails: NullableNetworkDetails;
}

export interface PartsLoadedData {
  frag: Fragment;
  part: Part | null;
  partsLoaded?: FragLoadedData[];
}

export interface FragDecryptedData {
  frag: Fragment;
  part: Part | null;
  payload: ArrayBuffer;
  stats: {
    tstart: number;
    tdecrypt: number;
  };
}

export interface FragParsingInitSegmentData {}

export interface FragParsingUserdataData {
  id: string;
  frag: Fragment;
  details: LevelDetails;
  samples: UserdataSample[];
}

export interface FragParsingMetadataData {
  id: string;
  frag: Fragment;
  details: LevelDetails;
  samples: MetadataSample[];
}

export interface FragParsedData {
  frag: Fragment;
  part: Part | null;
  chunkMeta: ChunkMetadata;
}

export interface FragBufferedData {
  stats: LoadStats;
  frag: Fragment;
  part: Part | null;
  id: PlaylistLevelType;
  chunkMeta?: ChunkMetadata;
}

export interface LevelsUpdatedData {
  levels: Array<Level>;
}

export interface KeyLoadingData {
  frag: Fragment;
}

export interface KeyLoadedData {
  frag: Fragment;
  keyInfo: KeyLoaderInfo;
}

export interface BackBufferData {
  bufferEnd: number;
}

/**
 * @deprecated Use BackBufferData
 */
export interface LiveBackBufferData extends BackBufferData {}

export interface SteeringManifestLoadedData {
  steeringManifest: SteeringManifest;
  url: string;
}

export interface AssetListLoadingData {
  event: InterstitialEventWithAssetList;
}

export interface AssetListLoadedData {
  event: InterstitialEventWithAssetList;
  assetListResponse: AssetListJSON;
  networkDetails: NullableNetworkDetails;
}

export interface InterstitialsUpdatedData {
  events: InterstitialEvent[];
  schedule: InterstitialScheduleItem[];
  durations: InterstitialScheduleDurations;
  removedIds: string[];
}

export interface InterstitialsBufferedToBoundaryData {
  events: InterstitialEvent[];
  schedule: InterstitialScheduleItem[];
  bufferingIndex: number;
  playingIndex: number;
}

export interface InterstitialAssetPlayerCreatedData {
  asset: InterstitialAssetItem;
  assetListIndex: number;
  assetListResponse?: AssetListJSON;
  event: InterstitialEvent;
  player: HlsAssetPlayer;
}

export interface InterstitialStartedData {
  event: InterstitialEvent;
  schedule: InterstitialScheduleItem[];
  scheduleIndex: number;
}

export interface InterstitialEndedData {
  event: InterstitialEvent;
  schedule: InterstitialScheduleItem[];
  scheduleIndex: number;
}

export interface InterstitialAssetStartedData {
  asset: InterstitialAssetItem;
  assetListIndex: number;
  event: InterstitialEvent;
  schedule: InterstitialScheduleItem[];
  scheduleIndex: number;
  player: HlsAssetPlayer;
}

export interface InterstitialAssetEndedData {
  asset: InterstitialAssetItem;
  assetListIndex: number;
  event: InterstitialEvent;
  schedule: InterstitialScheduleItem[];
  scheduleIndex: number;
  player: HlsAssetPlayer;
}

export type InterstitialAssetErrorData = {
  asset: InterstitialAssetItem | null;
  assetListIndex: number;
  event: InterstitialEvent | null;
  schedule: InterstitialScheduleItem[] | null;
  scheduleIndex: number;
  player: HlsAssetPlayer | null;
} & ErrorData;

export interface InterstitialsPrimaryResumed {
  schedule: InterstitialScheduleItem[];
  scheduleIndex: number;
}
