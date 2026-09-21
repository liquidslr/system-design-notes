import BaseLoader from './base-loader';
import { shouldRetry } from './error-helper';
import { logger } from './logger';
import ChunkCache from '../demux/chunk-cache';
import { isPromise } from '../demux/transmuxer';
import type { HlsConfig } from '../config';
import type {
  LoaderContext,
  LoaderOnProgress,
  LoaderResponse,
  LoaderStats,
} from '../types/loader';

export function fetchSupported() {
  if (
    // @ts-ignore
    self.fetch &&
    self.AbortController &&
    self.ReadableStream &&
    self.Request
  ) {
    try {
      new self.ReadableStream({}); // eslint-disable-line no-new
      return true;
    } catch (e) {
      /* noop */
    }
  }
  return false;
}

const BYTERANGE = /(\d+)-(\d+)\/(\d+)/;

class FetchLoader extends BaseLoader {
  private fetchSetup: NonNullable<HlsConfig['fetchSetup']>;
  private request: Promise<Request> | Request | null = null;
  private response: Response | null = null;
  private controller: AbortController | null = null;

  constructor(config: HlsConfig) {
    super();
    this.fetchSetup = config.fetchSetup || getRequest;
  }

  destroy(): void {
    this.request = null;
    super.destroy();
    this.response = null;
    this.controller = null;
    // @ts-ignore
    this.fetchSetup = null;
  }

  protected abortInternal(): void {
    self.clearTimeout(this.retryTimeout);
    if (this.controller && !this.stats.loading.end) {
      this.stats.aborted = true;
      this.controller.abort();
    }
  }

  protected getNetworkDetails(): Response | null {
    return this.response;
  }

  protected resetInternalLoader(): void {
    this.response = null;
  }

  protected loadInternal(): void {
    const { config, context, stats } = this;
    if (!config || !context) {
      return;
    }

    // Reset per-attempt stats
    stats.loading.first = 0;
    stats.loaded = 0;
    stats.aborted = false;

    // Create new AbortController for this attempt
    this.controller = new self.AbortController();

    const initParams = getRequestParameters(context, this.controller.signal);
    const isArrayBuffer = context.responseType === 'arraybuffer';
    const LENGTH = isArrayBuffer ? 'byteLength' : 'length';
    const { maxTimeToFirstByteMs, maxLoadTimeMs } = config.loadPolicy;

    this.request = this.fetchSetup(context, initParams);
    self.clearTimeout(this.requestTimeout);
    config.timeout =
      maxTimeToFirstByteMs && Number.isFinite(maxTimeToFirstByteMs)
        ? maxTimeToFirstByteMs
        : maxLoadTimeMs;
    this.requestTimeout = self.setTimeout(() => {
      this.loadtimeout();
    }, config.timeout);

    const fetchPromise = isPromise(this.request)
      ? this.request.then(self.fetch)
      : self.fetch(this.request);

    fetchPromise
      .then((response: Response): Promise<string | ArrayBuffer> => {
        this.response = response;

        const first = Math.max(self.performance.now(), stats.loading.start);

        self.clearTimeout(this.requestTimeout);
        config.timeout = maxLoadTimeMs;
        this.requestTimeout = self.setTimeout(
          () => {
            this.loadtimeout();
          },
          maxLoadTimeMs - (first - stats.loading.start),
        );

        if (!response.ok) {
          const { status, statusText } = response;
          throw new FetchError(
            statusText || 'fetch, bad network response',
            status,
            response,
          );
        }
        stats.loading.first = first;

        stats.total = getContentLength(response.headers) || stats.total;

        const onProgress = this.callbacks?.onProgress;
        if (onProgress && Number.isFinite(config.highWaterMark)) {
          return this.loadProgressively(
            response,
            stats,
            context,
            config.highWaterMark,
            onProgress,
          );
        }

        if (isArrayBuffer) {
          return response.arrayBuffer();
        }
        if (context.responseType === 'json') {
          return response.json();
        }
        return response.text();
      })
      .then((responseData: string | ArrayBuffer) => {
        const response = this.response;
        if (!response) {
          throw new Error('loader destroyed');
        }
        self.clearTimeout(this.requestTimeout);
        stats.loading.end = Math.max(
          self.performance.now(),
          stats.loading.first,
        );
        const total = responseData[LENGTH];
        if (total) {
          stats.loaded = stats.total = total;
        }

        const loaderResponse: LoaderResponse = {
          url: response.url,
          data: responseData,
          code: response.status,
        };

        const onProgress = this.callbacks?.onProgress;
        if (onProgress && !Number.isFinite(config.highWaterMark)) {
          onProgress(stats, context, responseData, response);
        }

        this.callbacks?.onSuccess(loaderResponse, stats, context, response);
      })
      .catch((error) => {
        self.clearTimeout(this.requestTimeout);
        if (stats.aborted) {
          return;
        }
        // CORS errors result in an undefined code. Set it to 0 here to align with XHR's behavior
        // when destroying, 'error' itself can be undefined
        const code: number = !error ? 0 : error.code || 0;
        const text: string = !error ? null : error.message;

        // Check errorRetry policy
        const retryConfig = config.loadPolicy.errorRetry;
        const retryCount = stats.retry;
        const response: LoaderResponse = {
          url: context.url,
          data: undefined,
          code,
        };
        if (shouldRetry(retryConfig, retryCount, false, response)) {
          this.retry(retryConfig);
        } else {
          logger.error(`${code} while loading ${context.url}`);
          this.callbacks?.onError(
            { code, text },
            context,
            error ? error.details : null,
            stats,
          );
        }
      });
  }

  getCacheAge(): number | null {
    let result: number | null = null;
    if (this.response) {
      const ageHeader = this.response.headers.get('age');
      result = ageHeader ? parseFloat(ageHeader) : null;
    }
    return result;
  }

  getResponseHeader(name: string): string | null {
    return this.response ? this.response.headers.get(name) : null;
  }

  private loadProgressively(
    response: Response,
    stats: LoaderStats,
    context: LoaderContext,
    highWaterMark: number = 0,
    onProgress: LoaderOnProgress<LoaderContext>,
  ): Promise<ArrayBuffer> {
    const chunkCache = new ChunkCache();
    const reader = (response.body as ReadableStream).getReader();

    const pump = (): Promise<ArrayBuffer> => {
      return reader
        .read()
        .then((data) => {
          if (data.done) {
            if (chunkCache.dataLength) {
              onProgress(stats, context, chunkCache.flush().buffer, response);
            }

            return Promise.resolve(new ArrayBuffer(0));
          }
          const chunk: Uint8Array<ArrayBuffer> = data.value;
          const len = chunk.length;
          stats.loaded += len;
          if (len < highWaterMark || chunkCache.dataLength) {
            // The current chunk is too small to to be emitted or the cache already has data
            // Push it to the cache
            chunkCache.push(chunk);
            if (chunkCache.dataLength >= highWaterMark) {
              // flush in order to join the typed arrays
              onProgress(stats, context, chunkCache.flush().buffer, response);
            }
          } else {
            // If there's nothing cached already, and the chache is large enough
            // just emit the progress event
            onProgress(stats, context, chunk.buffer, response);
          }
          return pump();
        })
        .catch(() => {
          /* aborted */
          return Promise.reject();
        });
    };

    return pump();
  }
}

function getRequestParameters(context: LoaderContext, signal): any {
  const initParams: any = {
    method: 'GET',
    mode: 'cors',
    credentials: 'same-origin',
    signal,
    headers: new self.Headers(Object.assign({}, context.headers)),
  };

  if (context.rangeEnd) {
    initParams.headers.set(
      'Range',
      'bytes=' + context.rangeStart + '-' + String(context.rangeEnd - 1),
    );
  }

  return initParams;
}

function getByteRangeLength(byteRangeHeader: string): number | undefined {
  const result = BYTERANGE.exec(byteRangeHeader);
  if (result) {
    return parseInt(result[2]) - parseInt(result[1]) + 1;
  }
}

function getContentLength(headers: Headers): number | undefined {
  const contentRange = headers.get('Content-Range');
  if (contentRange) {
    const byteRangeLength = getByteRangeLength(contentRange);
    if (Number.isFinite(byteRangeLength)) {
      return byteRangeLength;
    }
  }
  const contentLength = headers.get('Content-Length');
  if (contentLength) {
    return parseInt(contentLength);
  }
}

function getRequest(context: LoaderContext, initParams: any): Request {
  return new self.Request(context.url, initParams);
}

class FetchError extends Error {
  public code: number;
  public details: any;
  constructor(message: string, code: number, details: any) {
    super(message);
    this.code = code;
    this.details = details;
  }
}

export default FetchLoader;
