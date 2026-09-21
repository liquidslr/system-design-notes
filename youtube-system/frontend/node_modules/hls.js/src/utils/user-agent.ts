const ua = getNavigator('userAgent');
const vendor = getNavigator('vendor');

let chromeVersion: number | undefined;
let firefoxVersion: number | undefined;
let safariVersion: number | undefined;

function getNavigator(field: string) {
  try {
    return navigator[field] || '';
  } catch (e) {
    /* no-op */
  }
  return '';
}

export function userAgentSafariVersion(): number {
  if (safariVersion === undefined) {
    const result = ua.match(/Safari\/(\d+)/i);
    safariVersion = result ? parseInt(result[1]) : 0;
  }
  return safariVersion;
}

export function userAgentChromeVersion(): number {
  if (chromeVersion === undefined) {
    const result = ua.match(/Chrome\/(\d+)/i);
    chromeVersion = result ? parseInt(result[1]) : 0;
  }
  return chromeVersion;
}

export function userAgentFirefoxVersion(): number {
  if (firefoxVersion === undefined) {
    const result = ua.match(/Firefox\/(\d+)/i);
    firefoxVersion = result ? parseInt(result[1]) : 0;
  }
  return firefoxVersion;
}

export function userAgentHevcSupportIsInaccurate() {
  return /\(Windows.+Firefox\//i.test(ua);
}

export function userAgentIsIOSLike() {
  return vendor.indexOf('Apple') > -1 || /iPhone|iPad|iPod/.test(ua);
}

export function userAgentIsAndroidLike() {
  return /Android/.test(ua);
}
