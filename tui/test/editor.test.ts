import { expect, test } from "vitest";
import * as e from "../src/lib/editor";

const at = (value: string, cursor: number): e.Editor => ({ value, cursor });

test("typing and pasting insert at the cursor and normalise line endings", () => {
  expect(e.insert(at("ac", 1), "b")).toEqual(at("abc", 2));
  expect(e.insert(at("", 0), "a\r\nb\rc")).toEqual(at("a\nb\nc", 5));
});

test("backspace and delete stop at the edges", () => {
  expect(e.backspace(at("abc", 0))).toEqual(at("abc", 0));
  expect(e.backspace(at("abc", 2))).toEqual(at("ac", 1));
  expect(e.remove(at("abc", 3))).toEqual(at("abc", 3));
  expect(e.remove(at("abc", 1))).toEqual(at("ac", 1));
});

test("word movement and deletion skip whitespace", () => {
  expect(e.wordLeft(at("one two  three", 14))).toEqual(at("one two  three", 9));
  expect(e.wordRight(at("one two", 0))).toEqual(at("one two", 3));
  expect(e.deleteWord(at("one two", 7))).toEqual(at("one ", 4));
});

test("line operations work inside a multi-line value", () => {
  const value = "first\nsecond\nthird";
  expect(e.lineStart(at(value, 9))).toEqual(at(value, 6));
  expect(e.lineEnd(at(value, 8))).toEqual(at(value, 12));
  expect(e.deleteToLineStart(at(value, 9))).toEqual(at("first\nond\nthird", 6));
  expect(e.deleteToLineEnd(at(value, 8))).toEqual(at("first\nse\nthird", 8));
  expect(e.lineCount(at(value, 0))).toBe(3);
});

test("up and down keep the column and clamp to shorter lines", () => {
  const value = "abcdef\nab\nabcdef";
  expect(e.up(at(value, 12))).toEqual(at(value, 9));
  expect(e.up(at(value, 9))).toEqual(at(value, 2));
  expect(e.down(at(value, 5))).toEqual(at(value, 9));
  expect(e.down(at(value, 15))).toEqual(at(value, 15));
  expect(e.onFirstLine(at(value, 3))).toBe(true);
  expect(e.onLastLine(at(value, 14))).toBe(true);
});
