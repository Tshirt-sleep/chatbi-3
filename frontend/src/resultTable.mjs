function compareValues(left, right) {
  if (left === null && right === null) return 0;
  if (left === null) return 1;
  if (right === null) return -1;
  const numericPattern = /^-?\d+(?:\.\d+)?$/;
  const leftText = String(left);
  const rightText = String(right);
  if (numericPattern.test(leftText) && numericPattern.test(rightText)) {
    return Number(leftText) - Number(rightText);
  }
  return leftText.localeCompare(rightText, "zh-CN", {
    numeric: true,
    sensitivity: "base",
  });
}

export function sortResultRows(rows, sort) {
  if (!sort) return [...rows];
  return rows
    .map((row, index) => ({ row, index }))
    .sort((left, right) => {
      const leftValue = sort.key === "label" ? left.row.label : left.row.values[sort.key] ?? null;
      const rightValue = sort.key === "label" ? right.row.label : right.row.values[sort.key] ?? null;
      if (leftValue === null || rightValue === null) {
        const nullOrder = compareValues(leftValue, rightValue);
        return nullOrder === 0 ? left.index - right.index : nullOrder;
      }
      const comparison = compareValues(leftValue, rightValue);
      return comparison === 0
        ? left.index - right.index
        : comparison * (sort.direction === "asc" ? 1 : -1);
    })
    .map(({ row }) => row);
}

function csvField(value) {
  let text = value === null ? "" : String(value);
  const isNumeric = /^-?\d+(?:\.\d+)?$/.test(text);
  if (!isNumeric && /^[=+\-@]/.test(text.trimStart())) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}

export function createResultCsv(rows, keys, columnLabels) {
  const headers = ["名称", ...keys.map((key) => columnLabels[key] ?? key)];
  const records = rows.map((row) => [row.label, ...keys.map((key) => row.values[key] ?? null)]);
  const csv = [headers, ...records]
    .map((record) => record.map(csvField).join(","))
    .join("\r\n");
  return `\uFEFF${csv}`;
}
