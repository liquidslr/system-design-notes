import type { StringReader, StringWriter } from './strings';

export const comma = ','.charCodeAt(0);
export const semicolon = ';'.charCodeAt(0);

const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
const intToChar = new Uint8Array(64); // 64 possible chars.
const charToInt = new Uint8Array(128); // z is 122 in ASCII

for (let i = 0; i < chars.length; i++) {
  const c = chars.charCodeAt(i);
  intToChar[i] = c;
  charToInt[c] = i;
}

export function decodeInteger(reader: StringReader): number {
  let value = 0;
  let shift = 0;
  let integer = 0;

  do {
    const c = reader.next();
    integer = charToInt[c];
    value |= (integer & 31) << shift;
    shift += 5;
  } while (integer & 32);

  return value;
}

export function decodeSign(num: number): number {
  return num & 1 ? -0x80000000 | -(num >>> 1) : num >>> 1;
}

export function encodeInteger(builder: StringWriter, num: number) {
  do {
    let clamped = num & 0b011111;
    num >>>= 5;
    if (num > 0) clamped |= 0b100000;
    builder.write(intToChar[clamped]);
  } while (num > 0);
}

export function encodeSign(num: number): number {
  return num < 0 ? (-num << 1) | 1 : num << 1;
}

export function hasMoreVlq(reader: StringReader, max: number) {
  if (reader.pos >= max) return false;
  return reader.peek() !== comma;
}
