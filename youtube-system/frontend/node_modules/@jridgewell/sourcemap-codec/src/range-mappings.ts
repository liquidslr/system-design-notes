import { StringReader, StringWriter } from './strings';
import { decodeInteger, encodeInteger, semicolon } from './vlq';

export type MappingIndex = number;
export type RangeMappings = MappingIndex[][];

export function decodeRangeMappings(input: string): RangeMappings {
  const { length } = input;
  const reader = new StringReader(input);
  const rangeMappings: RangeMappings = [];

  do {
    const semi = reader.indexOf(';');
    const indices: MappingIndex[] = [];
    let index = 0;

    while (reader.pos < semi) {
      index += decodeInteger(reader);
      indices.push(index);
    }

    rangeMappings.push(indices);
    reader.pos = semi + 1;
  } while (reader.pos <= length);

  return rangeMappings;
}

export function encodeRangeMappings(decoded: RangeMappings): string {
  if (decoded.length === 0) return '';

  const writer = new StringWriter();

  for (let i = 0; i < decoded.length; i++) {
    const indices = decoded[i];
    if (i > 0) writer.write(semicolon);

    let index = 0;
    for (let j = 0; j < indices.length; j++) {
      const offset = indices[j];
      encodeInteger(writer, offset - index);
      index = offset;
    }
  }

  return writer.flush();
}
