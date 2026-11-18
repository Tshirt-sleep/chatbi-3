import { cp, mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const frontendDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const sourceDir = resolve(frontendDir, "..", "product-intro");
const outputDir = resolve(frontendDir, "dist", "product-intro");

await mkdir(outputDir, { recursive: true });
for (const file of ["index.html", "styles.css", "script.js"]) {
  await cp(resolve(sourceDir, file), resolve(outputDir, file));
}
