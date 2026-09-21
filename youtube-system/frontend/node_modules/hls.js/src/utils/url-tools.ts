/**
 * Set a query parameter on a URL without re-encoding the rest of its query
 * string.
 *
 * `URLSearchParams.set` re-serializes the entire query using
 * application/x-www-form-urlencoded rules, percent-encoding characters like
 * `~`, `=` and `/` in parameters the playlist author wrote. Signed CDN tokens
 * carry those characters verbatim and are validated byte-for-byte, so
 * re-encoding them breaks token validation (see #7963). This helper
 * component-encodes only the inserted key/value pair and leaves existing
 * parameters untouched. Like `URLSearchParams.set`, an existing parameter
 * with the same key is replaced in place and duplicates are removed.
 */
export function setQueryParam(url: URL, key: string, value: string) {
  const encodedKey = encodeURIComponent(key);
  const param = `${encodedKey}=${encodeURIComponent(value)}`;
  let replaced = false;
  const params: string[] = [];
  url.search
    .substring(1)
    .split('&')
    .forEach((p) => {
      if (p === encodedKey || p.startsWith(encodedKey + '=')) {
        if (!replaced) {
          params.push(param);
          replaced = true;
        }
      } else if (p) {
        params.push(p);
      }
    });
  if (!replaced) {
    params.push(param);
  }
  url.search = params.join('&');
}
