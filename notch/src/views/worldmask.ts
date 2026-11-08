// CLOVE fork: the world, as dots: 72 × 28 cells of 5° (80°N to 60°S), 1 = land. Each row is 18 hex digits.
// Made from Natural Earth's 1:110m land (public domain) via world-atlas 2.0.2 (ISC).

export const MAP_COLS = 72;
export const MAP_ROWS = 28;
export const MAP_TOP_LAT = 80;
export const MAP_STEP = 5;

const ROWS = [
  "000973ff018081c000",
  "001ef87f00033ffffe",
  "7ffffffffe1f000000",
  "1fffde3007fffffffe",
  "0c7fcf0016ffffff18",
  "003fff8037ffffff90",
  "001fff001fffffff80",
  "001ffc003ffffffe80",
  "001ff8003cfffff500",
  "000ff0003ebffff200",
  "000790007ffffff000",
  "000180007fff3fe000",
  "0001e000fffe39c000",
  "000034007ffc11c800",
  "00000f007ffc000800",
  "00000fc003f800b000",
  "00000ff003f000a380",
  "00000ff803f00060c0",
  "00000ff803f0000280",
  "000007f003f4000f80",
  "000003f001ec001fc0",
  "000003c001e0001fe0",
  "000007c001c0001fe0",
  "0000078000000000c0",
  "000006000000000042",
  "000006000000000000",
  "000004000000000000",
  "000000000000000000",
];

/** Is the cell at (col, row) land? */
export function isLand(col: number, row: number): boolean {
  const hex = ROWS[row];
  if (!hex || col < 0 || col >= MAP_COLS) return false;
  return ((parseInt(hex[col >> 2], 16) >> (3 - (col & 3))) & 1) === 1;
}
