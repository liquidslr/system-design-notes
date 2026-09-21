import BaseLoader from './base-loader';
import { shouldRetry } from './error-helper';
import { logger } from './logger';
import type { HlsConfig } from '../config';
import type {
  LoaderConfiguration,
  LoaderContext,
  LoaderResponse,
} from '../types/loader';

const AGE_HEADER_LINE_REGEX = /^age:\s*[\d.]+\s*$/im;

class XhrLoader extends BaseLoader {
  private xhrSetup:
    | ((
        xhr: XMLHttpRequest,
        url: string,
        context: LoaderContext,
      ) => Promise<void> | void)
    | null;
  private loader: XMLHttpRequest | null = null;

  constructor(config: HlsConfig) {
    super();
    this.xhrSetup = config.xhrSetup || null;
  }

  destroy(): void {
    super.destroy();
    this.loader = null;
    this.xhrSetup = null;
  }

  protected abortInternal(): void {
    const loader = this.loader;
    self.clearTimeout(this.requestTimeout);
    self.clearTimeout(this.retryTimeout);
    if (loader) {
      loader.onreadystatechange = null;
      loader.onprogress = null;
      if (loader.readyState !== 4) {
        this.stats.aborted = true;
        loader.abort();
      }
    }
  }

  protected getNetworkDetails(): XMLHttpRequest | null {
    return this.loader;
  }

  protected resetInternalLoader(): void {
    this.loader = null;
  }

  protected loadInternal(): void {
    const { config, context } = this;
    if (!config || !context) {
      return;
    }
    const xhr = (this.loader = new self.XMLHttpRequest());

    const stats = this.stats;
    stats.loading.first = 0;
    stats.loaded = 0;
    stats.aborted = false;
    const xhrSetup = this.xhrSetup;

    if (xhrSetup) {
      Promise.resolve()
        .then(() => {
          if (this.loader !== xhr || this.stats.aborted) return;
          return xhrSetup.call(this, xhr, context.url, context);
        })
        .catch((error: Error) => {
          if (this.loader !== xhr || this.stats.aborted) return;
          xhr.open('GET', context.url, true);
          return xhrSetup.call(this, xhr, context.url, context);
        })
        .then(() => {
          if (this.loader !== xhr || this.stats.aborted) return;
          this.openAndSendXhr(xhr, context, config);
        })
        .catch((error: Error) => {
          // IE11 throws an exception on xhr.open if attempting to access an HTTP resource over HTTPS
          this.callbacks?.onError(
            { code: xhr.status, text: error.message },
            context,
            xhr,
            stats,
          );
          return;
        });
    } else {
      this.openAndSendXhr(xhr, context, config);
    }
  }

  private openAndSendXhr(
    xhr: XMLHttpRequest,
    context: LoaderContext,
    config: LoaderConfiguration,
  ): void {
    if (!xhr.readyState) {
      xhr.open('GET', context.url, true);
    }

    const headers = context.headers;
    const { maxTimeToFirstByteMs, maxLoadTimeMs } = config.loadPolicy;
    if (headers) {
      for (const header in headers) {
        xhr.setRequestHeader(header, headers[header]);
      }
    }

    if (context.rangeEnd) {
      xhr.setRequestHeader(
        'Range',
        `bytes=${context.rangeStart}-${context.rangeEnd - 1}`,
      );
    }

    xhr.onreadystatechange = this.readystatechange.bind(this);
    xhr.onprogress = this.loadprogress.bind(this);
    xhr.responseType = context.responseType as XMLHttpRequestResponseType;
    // setup timeout before we perform request
    self.clearTimeout(this.requestTimeout);
    config.timeout =
      maxTimeToFirstByteMs && Number.isFinite(maxTimeToFirstByteMs)
        ? maxTimeToFirstByteMs
        : maxLoadTimeMs;
    this.requestTimeout = self.setTimeout(
      this.loadtimeout.bind(this),
      config.timeout,
    );
    xhr.send();
  }

  private readystatechange(): void {
    const { context, loader: xhr, stats } = this;
    if (!context || !xhr) {
      return;
    }
    const readyState = xhr.readyState;
    const config = this.config as LoaderConfiguration;

    // don't proceed if xhr has been aborted
    if (stats.aborted) {
      return;
    }

    // >= HEADERS_RECEIVED
    if (readyState >= 2) {
      if (stats.loading.first === 0) {
        stats.loading.first = Math.max(
          self.performance.now(),
          stats.loading.start,
        );
        // readyState >= 2 AND readyState !==4 (readyState = HEADERS_RECEIVED || LOADING) rearm timeout as xhr not finished yet
        if (config.timeout !== config.loadPolicy.maxLoadTimeMs) {
          self.clearTimeout(this.requestTimeout);
          config.timeout = config.loadPolicy.maxLoadTimeMs;
          this.requestTimeout = self.setTimeout(
            this.loadtimeout.bind(this),
            config.loadPolicy.maxLoadTimeMs -
              (stats.loading.first - stats.loading.start),
          );
        }
      }

      if (readyState === 4) {
        self.clearTimeout(this.requestTimeout);
        xhr.onreadystatechange = null;
        xhr.onprogress = null;
        const status = xhr.status;
        // http status between 200 to 299 are all successful
        const useResponseText =
          xhr.responseType === 'text' ? xhr.responseText : null;
        if (status >= 200 && status < 300) {
          const data = useResponseText ?? xhr.response;
          if (data != null) {
            stats.loading.end = Math.max(
              self.performance.now(),
              stats.loading.first,
            );
            const len =
              xhr.responseType === 'arraybuffer'
                ? data.byteLength
                : data.length;
            stats.loaded = stats.total = len;
            stats.bwEstimate =
              (stats.total * 8000) / (stats.loading.end - stats.loading.first);
            const onProgress = this.callbacks?.onProgress;
            if (onProgress) {
              onProgress(stats, context, data, xhr);
            }
            const response: LoaderResponse = {
              url: xhr.responseURL,
              data: data,
              code: status,
            };
            if (
              context.rangeEnd &&
              len !== context.rangeEnd - context.rangeStart!
            ) {
              logger.warn(
                `Payload length ${len} does not match requested Range: bytes=${context.rangeStart}-${context.rangeEnd - 1}`,
              );
            }
            this.callbacks?.onSuccess(response, stats, context, xhr);
            return;
          }
        }

        // Handle bad status or nullish response
        const retryConfig = config.loadPolicy.errorRetry;
        const retryCount = stats.retry;
        // if max nb of retries reached or if http status between 400 and 499 (such error cannot be recovered, retrying is useless), return error
        const response: LoaderResponse = {
          url: context.url,
          data: undefined,
          code: status,
        };
        if (shouldRetry(retryConfig, retryCount, false, response)) {
          this.retry(retryConfig);
        } else {
          logger.error(`${status} while loading ${context.url}`);
          this.callbacks?.onError(
            { code: status, text: xhr.statusText },
            context,
            xhr,
            stats,
          );
        }
      }
    }
  }

  private loadprogress(event: ProgressEvent): void {
    const stats = this.stats;

    stats.loaded = event.loaded;
    if (event.lengthComputable) {
      stats.total = event.total;
    }
  }

  getCacheAge(): number | null {
    let result: number | null = null;
    if (
      this.loader &&
      AGE_HEADER_LINE_REGEX.test(this.loader.getAllResponseHeaders())
    ) {
      const ageHeader = this.loader.getResponseHeader('age');
      result = ageHeader ? parseFloat(ageHeader) : null;
    }
    return result;
  }

  getResponseHeader(name: string): string | null {
    if (
      this.loader &&
      new RegExp(`^${name}:\\s*[\\d.]+\\s*$`, 'im').test(
        this.loader.getAllResponseHeaders(),
      )
    ) {
      return this.loader.getResponseHeader(name);
    }
    return null;
  }
}

export default XhrLoader;
