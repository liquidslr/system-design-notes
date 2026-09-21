import { StringReader, StringWriter } from './strings';
import {
  comma,
  decodeInteger,
  decodeSign,
  encodeInteger,
  encodeSign,
  hasMoreVlq,
  semicolon,
} from './vlq';

const EMPTY: any[] = [];

type Line = number;
type Column = number;
type Kind = number;
type Name = number;
type Var = number;
type SourcesIndex = number;
type ScopesIndex = number;

type Mix<A, B, O> = (A & O) | (B & O);

export type OriginalScope = Mix<
  [Line, Column, Line, Column, Kind],
  [Line, Column, Line, Column, Kind, Name],
  { vars: Var[] }
>;

export type GeneratedRange = Mix<
  [Line, Column, Line, Column],
  [Line, Column, Line, Column, SourcesIndex, ScopesIndex],
  {
    callsite: CallSite | null;
    bindings: Binding[];
    isScope: boolean;
  }
>;
export type CallSite = [SourcesIndex, Line, Column];
type Binding = BindingExpressionRange[];
export type BindingExpressionRange = [Name] | [Name, Line, Column];

export function decodeOriginalScopes(input: string): OriginalScope[] {
  const { length } = input;
  const reader = new StringReader(input);
  const scopes: OriginalScope[] = [];
  const stack: OriginalScope[] = [];
  let line = 0;

  for (; reader.pos < length; reader.pos++) {
    line += decodeSign(decodeInteger(reader));
    const column = decodeSign(decodeInteger(reader));

    if (!hasMoreVlq(reader, length)) {
      const last = stack.pop()!;
      last[2] = line;
      last[3] = column;
      continue;
    }

    const kind = decodeSign(decodeInteger(reader));
    const fields = decodeSign(decodeInteger(reader));
    const hasName = fields & 0b0001;

    const scope: OriginalScope = (
      hasName
        ? [line, column, 0, 0, kind, decodeSign(decodeInteger(reader))]
        : [line, column, 0, 0, kind]
    ) as OriginalScope;

    let vars: Var[] = EMPTY;
    if (hasMoreVlq(reader, length)) {
      vars = [];
      do {
        const varsIndex = decodeSign(decodeInteger(reader));
        vars.push(varsIndex);
      } while (hasMoreVlq(reader, length));
    }
    scope.vars = vars;

    scopes.push(scope);
    stack.push(scope);
  }

  return scopes;
}

export function encodeOriginalScopes(scopes: OriginalScope[]): string {
  const writer = new StringWriter();

  for (let i = 0; i < scopes.length; ) {
    i = _encodeOriginalScopes(scopes, i, writer, [0]);
  }

  return writer.flush();
}

function _encodeOriginalScopes(
  scopes: OriginalScope[],
  index: number,
  writer: StringWriter,
  state: [
    number, // GenColumn
  ],
): number {
  const scope = scopes[index];
  const { 0: startLine, 1: startColumn, 2: endLine, 3: endColumn, 4: kind, vars } = scope;

  if (index > 0) writer.write(comma);

  encodeInteger(writer, encodeSign(startLine - state[0]));
  state[0] = startLine;
  encodeInteger(writer, encodeSign(startColumn));
  encodeInteger(writer, encodeSign(kind));

  const fields = scope.length === 6 ? 0b0001 : 0;
  encodeInteger(writer, encodeSign(fields));
  if (scope.length === 6) encodeInteger(writer, encodeSign(scope[5]));

  for (const v of vars) {
    encodeInteger(writer, encodeSign(v));
  }

  for (index++; index < scopes.length; ) {
    const next = scopes[index];
    const { 0: l, 1: c } = next;
    if (l > endLine || (l === endLine && c >= endColumn)) {
      break;
    }
    index = _encodeOriginalScopes(scopes, index, writer, state);
  }

  writer.write(comma);
  encodeInteger(writer, encodeSign(endLine - state[0]));
  state[0] = endLine;
  encodeInteger(writer, encodeSign(endColumn));

  return index;
}

export function decodeGeneratedRanges(input: string): GeneratedRange[] {
  const { length } = input;
  const reader = new StringReader(input);
  const ranges: GeneratedRange[] = [];
  const stack: GeneratedRange[] = [];

  let genLine = 0;
  let definitionSourcesIndex = 0;
  let definitionScopeIndex = 0;
  let callsiteSourcesIndex = 0;
  let callsiteLine = 0;
  let callsiteColumn = 0;
  let bindingLine = 0;
  let bindingColumn = 0;

  do {
    const semi = reader.indexOf(';');
    let genColumn = 0;

    for (; reader.pos < semi; reader.pos++) {
      genColumn += decodeSign(decodeInteger(reader));

      if (!hasMoreVlq(reader, semi)) {
        const last = stack.pop()!;
        last[2] = genLine;
        last[3] = genColumn;
        continue;
      }

      const fields = decodeSign(decodeInteger(reader));
      const hasDefinition = fields & 0b0001;
      const hasCallsite = fields & 0b0010;
      const hasScope = fields & 0b0100;

      let callsite: CallSite | null = null;
      let bindings: Binding[] = EMPTY;
      let range: GeneratedRange;
      if (hasDefinition) {
        const defSourcesIndex = definitionSourcesIndex + decodeSign(decodeInteger(reader));
        definitionScopeIndex =
          decodeSign(decodeInteger(reader)) +
          (definitionSourcesIndex === defSourcesIndex ? definitionScopeIndex : 0);

        definitionSourcesIndex = defSourcesIndex;
        range = [genLine, genColumn, 0, 0, defSourcesIndex, definitionScopeIndex] as GeneratedRange;
      } else {
        range = [genLine, genColumn, 0, 0] as GeneratedRange;
      }

      range.isScope = !!hasScope;

      if (hasCallsite) {
        const prevCsi = callsiteSourcesIndex;
        const prevLine = callsiteLine;
        callsiteSourcesIndex += decodeSign(decodeInteger(reader));
        const sameSource = prevCsi === callsiteSourcesIndex;
        callsiteLine = (sameSource ? callsiteLine : 0) + decodeSign(decodeInteger(reader));
        callsiteColumn =
          (sameSource && prevLine === callsiteLine ? callsiteColumn : 0) +
          decodeSign(decodeInteger(reader));

        callsite = [callsiteSourcesIndex, callsiteLine, callsiteColumn];
      }
      range.callsite = callsite;

      if (hasMoreVlq(reader, semi)) {
        bindings = [];
        do {
          bindingLine = genLine;
          bindingColumn = genColumn;
          const expressionsCount = decodeSign(decodeInteger(reader));
          let expressionRanges: BindingExpressionRange[];
          if (expressionsCount < -1) {
            expressionRanges = [[decodeSign(decodeInteger(reader))]];
            for (let i = -1; i > expressionsCount; i--) {
              const prevBl = bindingLine;
              bindingLine += decodeSign(decodeInteger(reader));
              bindingColumn =
                (bindingLine === prevBl ? bindingColumn : 0) + decodeSign(decodeInteger(reader));
              const expression = decodeSign(decodeInteger(reader));
              expressionRanges.push([expression, bindingLine, bindingColumn]);
            }
          } else {
            expressionRanges = [[expressionsCount]];
          }
          bindings.push(expressionRanges);
        } while (hasMoreVlq(reader, semi));
      }
      range.bindings = bindings;

      ranges.push(range);
      stack.push(range);
    }

    genLine++;
    reader.pos = semi + 1;
  } while (reader.pos < length);

  return ranges;
}

export function encodeGeneratedRanges(ranges: GeneratedRange[]): string {
  if (ranges.length === 0) return '';

  const writer = new StringWriter();

  for (let i = 0; i < ranges.length; ) {
    i = _encodeGeneratedRanges(ranges, i, writer, [0, 0, 0, 0, 0, 0, 0]);
  }

  return writer.flush();
}

function _encodeGeneratedRanges(
  ranges: GeneratedRange[],
  index: number,
  writer: StringWriter,
  state: [
    number, // GenLine
    number, // GenColumn
    number, // DefSourcesIndex
    number, // DefScopesIndex
    number, // CallSourcesIndex
    number, // CallLine
    number, // CallColumn
  ],
): number {
  const range = ranges[index];
  const {
    0: startLine,
    1: startColumn,
    2: endLine,
    3: endColumn,
    isScope,
    callsite,
    bindings,
  } = range;

  if (state[0] < startLine) {
    catchupLine(writer, state[0], startLine);
    state[0] = startLine;
    state[1] = 0;
  } else if (index > 0) {
    writer.write(comma);
  }

  encodeInteger(writer, encodeSign(range[1] - state[1]));
  state[1] = range[1];

  const fields =
    (range.length === 6 ? 0b0001 : 0) | (callsite ? 0b0010 : 0) | (isScope ? 0b0100 : 0);
  encodeInteger(writer, encodeSign(fields));

  if (range.length === 6) {
    const { 4: sourcesIndex, 5: scopesIndex } = range;
    if (sourcesIndex !== state[2]) {
      state[3] = 0;
    }
    encodeInteger(writer, encodeSign(sourcesIndex - state[2]));
    state[2] = sourcesIndex;
    encodeInteger(writer, encodeSign(scopesIndex - state[3]));
    state[3] = scopesIndex;
  }

  if (callsite) {
    const { 0: sourcesIndex, 1: callLine, 2: callColumn } = range.callsite!;
    if (sourcesIndex !== state[4]) {
      state[5] = 0;
      state[6] = 0;
    } else if (callLine !== state[5]) {
      state[6] = 0;
    }
    encodeInteger(writer, encodeSign(sourcesIndex - state[4]));
    state[4] = sourcesIndex;
    encodeInteger(writer, encodeSign(callLine - state[5]));
    state[5] = callLine;
    encodeInteger(writer, encodeSign(callColumn - state[6]));
    state[6] = callColumn;
  }

  if (bindings) {
    for (const binding of bindings) {
      if (binding.length > 1) encodeInteger(writer, encodeSign(-binding.length));
      const expression = binding[0][0];
      encodeInteger(writer, encodeSign(expression));
      let bindingStartLine = startLine;
      let bindingStartColumn = startColumn;
      for (let i = 1; i < binding.length; i++) {
        const expRange = binding[i];
        encodeInteger(writer, encodeSign(expRange[1]! - bindingStartLine));
        bindingStartLine = expRange[1]!;
        encodeInteger(writer, encodeSign(expRange[2]! - bindingStartColumn));
        bindingStartColumn = expRange[2]!;
        encodeInteger(writer, encodeSign(expRange[0]!));
      }
    }
  }

  for (index++; index < ranges.length; ) {
    const next = ranges[index];
    const { 0: l, 1: c } = next;
    if (l > endLine || (l === endLine && c >= endColumn)) {
      break;
    }
    index = _encodeGeneratedRanges(ranges, index, writer, state);
  }

  if (state[0] < endLine) {
    catchupLine(writer, state[0], endLine);
    state[0] = endLine;
    state[1] = 0;
  } else {
    writer.write(comma);
  }
  encodeInteger(writer, encodeSign(endColumn - state[1]));
  state[1] = endColumn;

  return index;
}

function catchupLine(writer: StringWriter, lastLine: number, line: number) {
  do {
    writer.write(semicolon);
  } while (++lastLine < line);
}
