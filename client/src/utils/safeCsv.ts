type CsvRow = Record<string, unknown>;

export function safeCsvCell(value: unknown): string {
  let text = value == null ? "" : String(value);
  const formulaLike = /^[\s\u0000-\u001f]*[=+@]/.test(text)
    || /^[\s\u0000-\u001f]*-(?!\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$)/.test(text);
  if (typeof value === "string" && formulaLike) text = "'" + text;
  return `"${text.replace(/"/g, '""')}"`;
}

export function serializeCsv(rows: CsvRow[], columns: [string, string][]): string {
  return "\uFEFF" + [
    columns.map(([label]) => safeCsvCell(label)).join(","),
    ...rows.map((row) => columns.map(([, key]) => safeCsvCell(row[key])).join(",")),
  ].join("\r\n");
}
