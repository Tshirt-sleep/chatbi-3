export type ResultTableSort = { key: string; direction: "asc" | "desc" } | null;
export type ResultTableRow = {
  label: string;
  values: Record<string, string | number | null>;
};

export function sortResultRows<Row extends ResultTableRow>(
  rows: readonly Row[],
  sort: ResultTableSort,
): Row[];

export function createResultCsv(
  rows: readonly ResultTableRow[],
  keys: readonly string[],
  columnLabels: Record<string, string>,
): string;
