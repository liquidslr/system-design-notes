export function base64Decode(base64encodedStr: string) {
  return Uint8Array.from(atob(base64encodedStr), (c) => c.charCodeAt(0));
}

export function bin2str(data: number[] | Uint8Array | Uint16Array): string {
  return String.fromCharCode.apply(null, data);
}
