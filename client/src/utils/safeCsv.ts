type CsvRow = Record<string, unknown>;

export function safeCsvCell(value: unknown): string {
  let text = value == null ? "" : String(value);
  let first = 0;
  while (first < text.length && (text.charCodeAt(first) <= 31 || /\s/.test(text[first]))) first++;
  const significant = text.slice(first);
  const formulaLike = /^[=+@]/.test(significant)
    || /^-(?!\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$)/.test(significant);
  if (typeof value === "string" && formulaLike) text = "'" + text;
  return `"${text.replace(/"/g, '""')}"`;
}

export function serializeCsv(rows: CsvRow[], columns: [string, string][]): string {
  return "\uFEFF" + [
    columns.map(([label]) => safeCsvCell(label)).join(","),
    ...rows.map((row) => columns.map(([, key]) => safeCsvCell(row[key])).join(",")),
  ].join("\r\n");
}
