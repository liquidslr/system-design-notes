import { ErrorDetails } from '../errors';
import type { LoaderConfig, LoadPolicy, RetryConfig } from '../config';
import type { ErrorData } from '../types/events';
import type { Level } from '../types/level';
import type { LoaderResponse } from '../types/loader';

export function isTimeoutError(error: ErrorData): boolean {
  switch (error.details) {
    case ErrorDetails.FRAG_LOAD_TIMEOUT:
    case ErrorDetails.KEY_LOAD_TIMEOUT:
    case ErrorDetails.LEVEL_LOAD_TIMEOUT:
    case ErrorDetails.MANIFEST_LOAD_TIMEOUT:
    case ErrorDetails.AUDIO_TRACK_LOAD_TIMEOUT:
    case ErrorDetails.SUBTITLE_TRACK_LOAD_TIMEOUT:
    case ErrorDetails.ASSET_LIST_LOAD_TIMEOUT:
      return true;
  }
  return false;
}

export function isKeyError(error: ErrorData): boolean {
  return error.details.startsWith('key');
}

export function isUnusableKeyError(error: ErrorData): boolean {
  return isKeyError(error) && !!error.frag && !error.frag.decryptdata;
}

export function getRetryConfig(
  loadPolicy: LoadPolicy,
  error: ErrorData,
): RetryConfig | null {
  const isTimeout = isTimeoutError(error);
  return loadPolicy.default[`${isTimeout ? 'timeout' : 'error'}Retry`];
}

export function getRetryDelay(
  retryConfig: RetryConfig,
  retryCount: number,
): number {
  // exponential backoff capped to max retry delay
  const backoffFactor =
    retryConfig.backoff === 'linear' ? 1 : Math.pow(2, retryCount);
  return Math.min(
    backoffFactor * retryConfig.retryDelayMs,
    retryConfig.maxRetryDelayMs,
  );
}

export function getLoaderConfigWithoutReties(
  loderConfig: LoaderConfig,
): LoaderConfig {
  return {
    ...loderConfig,
    ...{
      errorRetry: null,
      timeoutRetry: null,
    },
  };
}

export function shouldRetry(
  retryConfig: RetryConfig | null | undefined,
  retryCount: number,
  isTimeout: boolean,
  loaderResponse?: LoaderResponse | undefined,
): retryConfig is RetryConfig & boolean {
  if (!retryConfig) {
    return false;
  }
  const httpStatus = loaderResponse?.code;
  const retry =
    retryCount < retryConfig.maxNumRetry &&
    (retryForHttpStatus(httpStatus) || !!isTimeout);
  return retryConfig.shouldRetry
    ? retryConfig.shouldRetry(
        retryConfig,
        retryCount,
        isTimeout,
        loaderResponse,
        retry,
      )
    : retry;
}

export function retryForHttpStatus(httpStatus: number | undefined): boolean {
  // Do not retry on status 4xx, status 0 (CORS error), or undefined (decrypt/gap/parse error)
  return (
    offlineHttpStatus(httpStatus) ||
    (!!httpStatus && (httpStatus < 400 || httpStatus > 499))
  );
}

export function offlineHttpStatus(httpStatus: number | undefined): boolean {
  return httpStatus === 0 && navigator.onLine === false;
}

export function isPenaltyExpired(level: Level, expireMs: number): boolean {
  // A penalized level (loadError > 0) is excluded from ABR upswitch and error
  // recovery candidate selection. Its errors only clear when it successfully
  // buffers — but it can't buffer because it won't be selected — leaving the
  // player stuck at a lower quality until stopLoad. This allows a penalized
  // level to be re-elected once its penalty has expired.
  return (
    expireMs > 0 &&
    level.loadError > 0 &&
    level.loadErrorTime !== 0 &&
    self.performance.now() - level.loadErrorTime > expireMs
  );
}
