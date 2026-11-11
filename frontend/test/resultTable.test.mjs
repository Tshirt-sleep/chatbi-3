import assert from "node:assert/strict";
import test from "node:test";

import { createResultCsv, sortResultRows } from "../src/resultTable.mjs";

test("sorts numbers numerically and keeps equal values stable", () => {
  const rows = [
    { key: "a", label: "甲", values: { count: 9 } },
    { key: "b", label: "乙", values: { count: 2 } },
    { key: "c", label: "丙", values: { count: 2 } },
  ];
  assert.deepEqual(
    sortResultRows(rows, { key: "count", direction: "asc" }).map((row) => row.key),
    ["b", "c", "a"],
  );
  assert.deepEqual(
    sortResultRows(rows, { key: "count", direction: "desc" }).map((row) => row.key),
    ["a", "b", "c"],
  );
});

test("sorts names naturally and leaves nulls last in both directions", () => {
  const rows = [
    { key: "a", label: "商品 10", values: { amount: null } },
    { key: "b", label: "商品 2", values: { amount: -5 } },
    { key: "c", label: "商品 1", values: { amount: 12 } },
  ];
  assert.deepEqual(
    sortResultRows(rows, { key: "label", direction: "asc" }).map((row) => row.key),
    ["c", "b", "a"],
  );
  assert.deepEqual(
    sortResultRows(rows, { key: "amount", direction: "desc" }).map((row) => row.key),
    ["c", "b", "a"],
  );
});

test("exports current order, raw values, quoted delimiters and formula-safe text", () => {
  const rows = [
    {
      label: '品类, "推荐"\n二行',
      values: { amount: "-25.30", note: "  =HYPERLINK(1)" },
    },
    { label: "正常商品", values: { amount: 12, note: null } },
  ];
  const csv = createResultCsv(rows, ["amount", "note"], { amount: "金额", note: "备注" });
  assert.ok(csv.startsWith("\uFEFF"));
  assert.match(csv, /"品类, ""推荐""\n二行","-25\.30","'  =HYPERLINK\(1\)"/);
  assert.match(csv, /"正常商品","12",""/);
});
