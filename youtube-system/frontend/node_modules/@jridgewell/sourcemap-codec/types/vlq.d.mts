import type { StringReader, StringWriter } from './strings.mts';
export declare const comma: number;
export declare const semicolon: number;
export declare function decodeInteger(reader: StringReader): number;
export declare function decodeSign(num: number): number;
export declare function encodeInteger(builder: StringWriter, num: number): void;
export declare function encodeSign(num: number): number;
export declare function hasMoreVlq(reader: StringReader, max: number): boolean;
//# sourceMappingURL=vlq.d.ts.map