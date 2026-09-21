import { getRetryDelay, shouldRetry } from './error-helper';
import { logger } from './logger';
import { LoadStats } from '../loader/load-stats';
import type { RetryConfig } from '../config';
import type {
  Loader,
  LoaderCallbacks,
  LoaderConfiguration,
  LoaderContext,
} from '../types/loader';
import type { NullableNetworkDetails } from '../types/network-details';

export default abstract class BaseLoader implements Loader<LoaderContext> {
  protected requestTimeout?: number;
  protected retryTimeout?: number;
  protected retryDelay: number = 0;
  protected config: LoaderConfiguration | null = null;
  protected callbacks: LoaderCallbacks<LoaderContext> | null = null;
  public context: LoaderContext | null = null;
  public stats = new LoadStats();

  destroy(): void {
    this.callbacks = this.context = this.config = null;
    this.abortInternal();
    // @ts-ignore
    this.stats = null;
  }

  load(
    context: LoaderContext,
    config: LoaderConfiguration,
    callbacks: LoaderCallbacks<LoaderContext>,
  ): void {
    const stats = this.stats;
    if (stats.loading.start) {
      throw new Error('Loader can only be used once.');
    }
    stats.loading.start = self.performance.now();

    this.context = context;
    this.config = config;
    this.callbacks = callbacks;
    this.loadInternal();
  }

  abort(): void {
    this.abortInternal();
    if (this.callbacks?.onAbort) {
      this.callbacks.onAbort(
        this.stats,
        this.context as LoaderContext,
        this.getNetworkDetails(),
      );
    }
  }

  protected loadtimeout(): void {
    if (!this.config) return;
    const retryConfig = this.config.loadPolicy.timeoutRetry;
    const retryCount = this.stats.retry;
    if (shouldRetry(retryConfig, retryCount, true)) {
      this.retry(retryConfig);
    } else {
      logger.warn(`timeout while loading ${this.context?.url}`);
      const callbacks = this.callbacks;
      if (callbacks) {
        this.abortInternal();
        callbacks.onTimeout(
          this.stats,
          this.context as LoaderContext,
          this.getNetworkDetails(),
        );
      }
    }
  }

  protected retry(retryConfig: RetryConfig): void {
    const { context, stats } = this;
    this.retryDelay = getRetryDelay(retryConfig, stats.retry);
    stats.retry++;
    logger.warn(
      `${
        status ? 'HTTP Status ' + status : 'Timeout'
      } while loading ${context?.url}, retrying ${stats.retry}/${
        retryConfig.maxNumRetry
      } in ${this.retryDelay}ms`,
    );
    // abort and reset internal state
    this.abortInternal();
    this.resetInternalLoader();
    // schedule retry
    self.clearTimeout(this.retryTimeout);
    this.retryTimeout = self.setTimeout(
      () => this.loadInternal(),
      this.retryDelay,
    );
  }

  protected abstract loadInternal(): void;
  protected abstract abortInternal(): void;
  protected abstract getNetworkDetails(): NullableNetworkDetails;
  protected abstract resetInternalLoader(): void;
  abstract getCacheAge(): number | null;
  abstract getResponseHeader(name: string): string | null;
}
