export interface Editor {
  value: string;
  cursor: number;
}

export const emptyEditor: Editor = { value: "", cursor: 0 };

export function insert(editor: Editor, text: string): Editor {
  const clean = text.replace(/\r\n?/g, "\n");
  return {
    value: editor.value.slice(0, editor.cursor) + clean + editor.value.slice(editor.cursor),
    cursor: editor.cursor + clean.length,
  };
}

export function backspace(editor: Editor): Editor {
  if (editor.cursor === 0) {
    return editor;
  }
  return {
    value: editor.value.slice(0, editor.cursor - 1) + editor.value.slice(editor.cursor),
    cursor: editor.cursor - 1,
  };
}

export function remove(editor: Editor): Editor {
  if (editor.cursor >= editor.value.length) {
    return editor;
  }
  return { ...editor, value: editor.value.slice(0, editor.cursor) + editor.value.slice(editor.cursor + 1) };
}

export function left(editor: Editor): Editor {
  return { ...editor, cursor: Math.max(0, editor.cursor - 1) };
}

export function right(editor: Editor): Editor {
  return { ...editor, cursor: Math.min(editor.value.length, editor.cursor + 1) };
}

function wordStart(value: string, from: number): number {
  let index = from;
  while (index > 0 && /\s/.test(value[index - 1] ?? "")) {
    index -= 1;
  }
  while (index > 0 && !/\s/.test(value[index - 1] ?? "")) {
    index -= 1;
  }
  return index;
}

function wordEnd(value: string, from: number): number {
  let index = from;
  while (index < value.length && /\s/.test(value[index] ?? "")) {
    index += 1;
  }
  while (index < value.length && !/\s/.test(value[index] ?? "")) {
    index += 1;
  }
  return index;
}

export function wordLeft(editor: Editor): Editor {
  return { ...editor, cursor: wordStart(editor.value, editor.cursor) };
}

export function wordRight(editor: Editor): Editor {
  return { ...editor, cursor: wordEnd(editor.value, editor.cursor) };
}

export function deleteWord(editor: Editor): Editor {
  const start = wordStart(editor.value, editor.cursor);
  return {
    value: editor.value.slice(0, start) + editor.value.slice(editor.cursor),
    cursor: start,
  };
}

function lineBounds(value: string, cursor: number): { start: number; end: number } {
  const start = value.lastIndexOf("\n", cursor - 1) + 1;
  const newline = value.indexOf("\n", cursor);
  return { start, end: newline === -1 ? value.length : newline };
}

export function lineStart(editor: Editor): Editor {
  return { ...editor, cursor: lineBounds(editor.value, editor.cursor).start };
}

export function lineEnd(editor: Editor): Editor {
  return { ...editor, cursor: lineBounds(editor.value, editor.cursor).end };
}

export function deleteToLineStart(editor: Editor): Editor {
  const { start } = lineBounds(editor.value, editor.cursor);
  return { value: editor.value.slice(0, start) + editor.value.slice(editor.cursor), cursor: start };
}

export function deleteToLineEnd(editor: Editor): Editor {
  const { end } = lineBounds(editor.value, editor.cursor);
  return { ...editor, value: editor.value.slice(0, editor.cursor) + editor.value.slice(end) };
}

export function lineCount(editor: Editor): number {
  return editor.value.split("\n").length;
}

export function onFirstLine(editor: Editor): boolean {
  return !editor.value.slice(0, editor.cursor).includes("\n");
}

export function onLastLine(editor: Editor): boolean {
  return !editor.value.slice(editor.cursor).includes("\n");
}

export function up(editor: Editor): Editor {
  const { start } = lineBounds(editor.value, editor.cursor);
  if (start === 0) {
    return editor;
  }
  const column = editor.cursor - start;
  const previous = lineBounds(editor.value, start - 1);
  return { ...editor, cursor: Math.min(previous.start + column, previous.end) };
}

export function down(editor: Editor): Editor {
  const { start, end } = lineBounds(editor.value, editor.cursor);
  if (end >= editor.value.length) {
    return editor;
  }
  const column = editor.cursor - start;
  const next = lineBounds(editor.value, end + 1);
  return { ...editor, cursor: Math.min(next.start + column, next.end) };
}

export function setValue(value: string): Editor {
  return { value, cursor: value.length };
}
