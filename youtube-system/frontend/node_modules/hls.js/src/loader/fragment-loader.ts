import { ErrorDetails, ErrorTypes } from '../errors';
import { LoaderContextType } from '../types/loader';
import { getLoaderConfigWithoutReties } from '../utils/error-helper';
import type { BaseSegment, Fragment, Part } from './fragment';
import type { HlsConfig } from '../config';
import type {
  ErrorData,
  FragLoadedData,
  PartsLoadedData,
} from '../types/events';
import type {
  FragmentLoaderContext,
  Loader,
  LoaderCallbacks,
  LoaderConfiguration,
} from '../types/loader';
import type { NullableNetworkDetails } from '../types/network-details';

const MIN_CHUNK_SIZE = Math.pow(2, 17); // 128kb

export default class FragmentLoader {
  private readonly config: HlsConfig;
  private loader: Loader<FragmentLoaderContext> | null = null;
  private partLoadTimeout: number = -1;

  constructor(config: HlsConfig) {
    this.config = config;
  }

  destroy() {
    if (this.loader) {
      this.loader.destroy();
      this.loader = null;
    }
  }

  abort() {
    if (this.loader) {
      // Abort the loader for current fragment. Only one may load at any given time
      this.loader.abort();
    }
  }

  load(
    frag: Fragment,
    isIFrame?: boolean,
    onProgress?: FragmentLoadProgressCallback,
    progressGate?: Promise<void>,
  ): Promise<FragLoadedData> {
    const url = frag.url;
    if (!url) {
      return Promise.reject(
        new LoadError({
          type: ErrorTypes.NETWORK_ERROR,
          details: ErrorDetails.FRAG_LOAD_ERROR,
          fatal: false,
          frag,
          error: new Error(
            `Fragment does not have a ${url ? 'part list' : 'url'}`,
          ),
          networkDetails: null,
        }),
      );
    }
    this.abort();

    const config = this.config;
    const FragmentILoader = config.fLoader;
    const DefaultILoader = config.loader;

    return new Promise((resolve, reject) => {
      if (this.loader) {
        this.loader.destroy();
      }
      if (frag.gap) {
        if (frag.tagList.some((tags) => tags[0] === 'GAP')) {
          reject(createGapLoadError(frag));
          return;
        } else {
          // Reset temporary treatment as GAP tag
          frag.gap = false;
        }
      }
      const loader = (this.loader = FragmentILoader
        ? new FragmentILoader(config)
        : (new DefaultILoader(config) as Loader<FragmentLoaderContext>));
      const loaderContext = createLoaderContext(frag, null, isIFrame);
      frag.loader = loader;
      const loadPolicy = getLoaderConfigWithoutReties(
        config.fragLoadPolicy.default,
      );
      const loaderConfig: LoaderConfiguration = {
        loadPolicy,
        timeout: loadPolicy.maxLoadTimeMs,
        maxRetry: 0,
        retryDelay: 0,
        maxRetryDelay: 0,
        highWaterMark: frag.sn === 'initSegment' ? Infinity : MIN_CHUNK_SIZE,
      };
      // Assign frag stats to the loader's stats reference
      loader.stats.retry = frag.stats.retry;
      frag.stats = loader.stats;
      const callbacks: LoaderCallbacks<FragmentLoaderContext> = {
        onSuccess: (response, stats, context, networkDetails) => {
          this.resetLoader(frag, loader);
          let payload = response.data as ArrayBuffer;
          if (context.resetIV && frag.decryptdata) {
            frag.decryptdata.iv = new Uint8Array(payload.slice(0, 16));
            payload = payload.slice(16);
          }
          resolve({
            frag,
            part: null,
            payload,
            networkDetails,
          });
        },
        onError: (response, context, networkDetails, stats) => {
          this.resetLoader(frag, loader);
          reject(
            new LoadError({
              type: ErrorTypes.NETWORK_ERROR,
              details: ErrorDetails.FRAG_LOAD_ERROR,
              fatal: false,
              frag,
              response: { url, data: undefined, ...response },
              error: new Error(`HTTP Error ${response.code} ${response.text}`),
              networkDetails,
              stats,
            }),
          );
        },
        onAbort: (stats, context, networkDetails) => {
          this.resetLoader(frag, loader);
          reject(
            new LoadError({
              type: ErrorTypes.NETWORK_ERROR,
              details: ErrorDetails.INTERNAL_ABORTED,
              fatal: false,
              frag,
              error: new Error('Aborted'),
              networkDetails,
              stats,
            }),
          );
        },
        onTimeout: (stats, context, networkDetails) => {
          this.resetLoader(frag, loader);
          reject(
            new LoadError({
              type: ErrorTypes.NETWORK_ERROR,
              details: ErrorDetails.FRAG_LOAD_TIMEOUT,
              fatal: false,
              frag,
              error: new Error(`Timeout after ${loaderConfig.timeout}ms`),
              networkDetails,
              stats,
            }),
          );
        },
      };
      if (onProgress) {
        const onProgressGated = this.gateProgress(onProgress, progressGate);

        callbacks.onProgress = (stats, context, data, networkDetails) =>
          onProgressGated({
            frag,
            part: null,
            payload: data as ArrayBuffer,
            networkDetails,
          });
      }
      loader.load(loaderContext, loaderConfig, callbacks);
    });
  }

  /*
   When a progressGate is provided, buffer incoming chunks until the
   gate promise resolves, then flush them in arrival order. This
   ensuring the transmuxer receives init data before the first chunk.
   Which is important when progressively loading media fragments.
  */
  private gateProgress(
    onProgress: FragmentLoadProgressCallback,
    progressGate?: Promise<void>,
  ): FragmentLoadProgressCallback {
    let handleChunk = onProgress;
    if (progressGate) {
      const pendingChunks: FragLoadedData[] = [];
      let gateDone = false;
      progressGate
        .then(() => {
          gateDone = true;
          pendingChunks.forEach((chunk) => onProgress(chunk));
          pendingChunks.length = 0;
        })
        .catch(() => {});
      handleChunk = (data) => {
        if (gateDone) {
          onProgress(data);
        } else {
          pendingChunks.push(data as FragLoadedData);
        }
      };
    }
    return handleChunk;
  }

  public loadPart(
    frag: Fragment,
    part: Part,
    onProgress: FragmentLoadProgressCallback,
  ): Promise<FragLoadedData> {
    this.abort();

    const config = this.config;
    const FragmentILoader = config.fLoader;
    const DefaultILoader = config.loader;

    return new Promise((resolve, reject) => {
      if (this.loader) {
        this.loader.destroy();
      }
      if (frag.gap || part.gap) {
        reject(createGapLoadError(frag, part));
        return;
      }
      const loader = (this.loader = FragmentILoader
        ? new FragmentILoader(config)
        : (new DefaultILoader(config) as Loader<FragmentLoaderContext>));
      const loaderContext = createLoaderContext(frag, part);
      frag.loader = loader;
      // Should we define another load policy for parts?
      const loadPolicy = getLoaderConfigWithoutReties(
        config.fragLoadPolicy.default,
      );
      const loaderConfig: LoaderConfiguration = {
        loadPolicy,
        timeout: loadPolicy.maxLoadTimeMs,
        maxRetry: 0,
        retryDelay: 0,
        maxRetryDelay: 0,
        highWaterMark: MIN_CHUNK_SIZE,
      };
      // Assign part stats to the loader's stats reference
      part.stats = loader.stats;
      loader.load(loaderContext, loaderConfig, {
        onSuccess: (response, stats, context, networkDetails) => {
          this.resetLoader(frag, loader);
          this.updateStatsFromPart(frag, part);
          const partLoadedData: FragLoadedData = {
            frag,
            part,
            payload: response.data as ArrayBuffer,
            networkDetails,
          };
          onProgress(partLoadedData);
          resolve(partLoadedData);
        },
        onError: (response, context, networkDetails, stats) => {
          this.resetLoader(frag, loader);
          reject(
            new LoadError({
              type: ErrorTypes.NETWORK_ERROR,
              details: ErrorDetails.FRAG_LOAD_ERROR,
              fatal: false,
              frag,
              part,
              response: {
                url: loaderContext.url,
                data: undefined,
                ...response,
              },
              error: new Error(`HTTP Error ${response.code} ${response.text}`),
              networkDetails,
              stats,
            }),
          );
        },
        onAbort: (stats, context, networkDetails) => {
          frag.stats.aborted = part.stats.aborted;
          this.resetLoader(frag, loader);
          reject(
            new LoadError({
              type: ErrorTypes.NETWORK_ERROR,
              details: ErrorDetails.INTERNAL_ABORTED,
              fatal: false,
              frag,
              part,
              error: new Error('Aborted'),
              networkDetails,
              stats,
            }),
          );
        },
        onTimeout: (stats, context, networkDetails) => {
          this.resetLoader(frag, loader);
          reject(
            new LoadError({
              type: ErrorTypes.NETWORK_ERROR,
              details: ErrorDetails.FRAG_LOAD_TIMEOUT,
              fatal: false,
              frag,
              part,
              error: new Error(`Timeout after ${loaderConfig.timeout}ms`),
              networkDetails,
              stats,
            }),
          );
        },
      });
    });
  }

  private updateStatsFromPart(frag: Fragment, part: Part) {
    const fragStats = frag.stats;
    const partStats = part.stats;
    const partTotal = partStats.total;
    fragStats.loaded += partStats.loaded;
    if (partTotal) {
      const estTotalParts = Math.round(frag.duration / part.duration);
      const estLoadedParts = Math.min(
        Math.round(fragStats.loaded / partTotal),
        estTotalParts,
      );
      const estRemainingParts = estTotalParts - estLoadedParts;
      const estRemainingBytes =
        estRemainingParts * Math.round(fragStats.loaded / estLoadedParts);
      fragStats.total = fragStats.loaded + estRemainingBytes;
    } else {
      fragStats.total = Math.max(fragStats.loaded, fragStats.total);
    }
    const fragLoading = fragStats.loading;
    const partLoading = partStats.loading;
    if (fragLoading.start) {
      // add to fragment loader latency
      fragLoading.first += partLoading.first - partLoading.start;
    } else {
      fragLoading.start = partLoading.start;
      fragLoading.first = partLoading.first;
    }
    fragLoading.end = partLoading.end;
  }

  private resetLoader(frag: Fragment, loader: Loader<FragmentLoaderContext>) {
    frag.loader = null;
    frag.url = null;
    if (this.loader === loader) {
      self.clearTimeout(this.partLoadTimeout);
      this.loader = null;
    }
    loader.destroy();
  }
}

function createLoaderContext(
  frag: Fragment,
  part: Part | null = null,
  isIFrame?: boolean,
): FragmentLoaderContext {
  const segment: BaseSegment = part || frag;
  const loaderContext: FragmentLoaderContext = {
    type: LoaderContextType.MEDIA_FRAGMENT,
    frag,
    part,
    responseType: 'arraybuffer',
    url: segment.url,
    headers: {},
    rangeStart: 0,
    rangeEnd: 0,
  };
  const aesAdjustments = getAESAdjustments(frag, part, isIFrame);
  if (aesAdjustments.resetIV) {
    loaderContext.resetIV = true;
  }
  if (aesAdjustments.byteRange) {
    loaderContext.rangeStart = aesAdjustments.byteRange.start;
    loaderContext.rangeEnd = aesAdjustments.byteRange.end;
  }
  return loaderContext;
}

export function getAESAdjustments(
  frag: Fragment,
  part: Part | null = null,
  isIFrame?: boolean,
) {
  const result: {
    resetIV?: boolean;
    byteRange?: { start: number; end: number };
    decryptRange?: { start: number; end: number };
  } = {};
  const segment: BaseSegment = part || frag;
  const start = segment.byteRangeStartOffset as number;
  const end = segment.byteRangeEndOffset as number;
  if (Number.isFinite(start) && Number.isFinite(end)) {
    if (
      (frag.sn === 'initSegment' || isIFrame) &&
      isMethodFullSegmentAesCbc(frag.decryptdata?.method)
    ) {
      // MAP segment encrypted with method 'AES-128' or 'AES-256' (cbc), when served with HTTP Range,
      // has the unencrypted size specified in the range.
      // Ref: https://tools.ietf.org/html/draft-pantos-hls-rfc8216bis-08#section-6.3.6
      let byteRangeStart = Math.floor(start / 16) * 16; // round down to 16-byte boundary;
      const byteRangeEnd = Math.ceil(end / 16) * 16; // round up to 16-byte boundary
      result.decryptRange = {
        start: start - byteRangeStart,
        end: end - byteRangeStart,
      };
      if (byteRangeStart >= 16) {
        result.resetIV = true;
        byteRangeStart = byteRangeStart - 16;
      }
      result.byteRange = {
        start: byteRangeStart,
        end: byteRangeEnd,
      };
    } else {
      result.byteRange = {
        start,
        end,
      };
    }
  }
  return result;
}

function createGapLoadError(frag: Fragment, part?: Part): LoadError {
  const error = new Error(`GAP ${frag.gap ? 'tag' : 'attribute'} found`);
  const errorData: FragLoadFailResult = {
    type: ErrorTypes.MEDIA_ERROR,
    details: ErrorDetails.FRAG_GAP,
    fatal: false,
    frag,
    error,
    networkDetails: null,
  };
  if (part) {
    errorData.part = part;
  }
  (part ? part : frag).stats.aborted = true;
  return new LoadError(errorData);
}

function isMethodFullSegmentAesCbc(method) {
  return method === 'AES-128' || method === 'AES-256';
}

export class LoadError extends Error {
  public readonly data: FragLoadFailResult;
  constructor(data: FragLoadFailResult) {
    super(data.error.message);
    this.data = data;
  }
}

export interface FragLoadFailResult extends ErrorData {
  frag: Fragment;
  part?: Part;
  response?: {
    data: any;
    // error status code
    code: number;
    // error description
    text: string;
    url: string;
  };
  networkDetails: NullableNetworkDetails;
}

export type FragmentLoadProgressCallback = (
  result: FragLoadedData | PartsLoadedData,
) => void;
