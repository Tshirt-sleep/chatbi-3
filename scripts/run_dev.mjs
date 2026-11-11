import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";

const root = process.cwd();
const pythonCandidates = process.platform === "win32"
  ? [resolve(root, ".venv", "Scripts", "python.exe"), "python"]
  : [resolve(root, ".venv", "bin", "python"), "python3"];
const python = pythonCandidates.find((candidate) => candidate === "python" || candidate === "python3" || existsSync(candidate));
const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
const npmCli = process.env.npm_execpath;
const frontendArgs = npmCli
  ? [npmCli, "run", "dev"]
  : ["run", "dev"];
if (!python) {
  console.error("Python was not found. Run .\\scripts\\setup.ps1 first.");
  process.exit(1);
}

const windows = process.platform === "win32";
const children = [
  spawn(python, ["-m", "uvicorn", "backend.chatbi.main:app", "--reload", "--host", "127.0.0.1", "--port", "8000"], {
    cwd: root,
    stdio: "inherit",
    env: { ...process.env, CHATBI_DEBUG_ENABLED: process.env.CHATBI_DEBUG_ENABLED ?? "true" },
  }),
  spawn(npmCli ? process.execPath : npmCommand, frontendArgs, {
    cwd: resolve(root, "frontend"),
    stdio: "inherit",
    shell: false,
    windowsVerbatimArguments: !npmCli && windows,
  }),
];

let stopping = false;
function stopAll(exitCode = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) {
    if (!child.killed) child.kill("SIGTERM");
  }
  setTimeout(() => process.exit(exitCode), 200);
}

for (const child of children) {
  child.on("error", (error) => {
    console.error(error.message);
    stopAll(1);
  });
  child.on("exit", (code) => {
    if (!stopping && code !== 0) stopAll(code ?? 1);
  });
}

process.on("SIGINT", () => stopAll(0));
process.on("SIGTERM", () => stopAll(0));
console.log("Local-only services starting: http://127.0.0.1:5173 and http://127.0.0.1:8000/docs");
