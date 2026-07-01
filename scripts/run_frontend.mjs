import { spawn } from "node:child_process";
import { readFileSync, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const frontendDir = resolve(root, "frontend");
const runtimeEnvPath = resolve(root, ".vscode", ".runtime.env");

const runtimeEnv = readRuntimeEnv(runtimeEnvPath);
const frontendPort = runtimeEnv.FRONTEND_PORT || "5173";
if (!/^\d+$/.test(frontendPort)) {
  throw new Error(`Invalid FRONTEND_PORT: ${frontendPort}`);
}
const npmCommand = "npm";
const npmArgs = ["run", "dev", "--", "--host", "127.0.0.1", "--port", frontendPort, "--strictPort", "--clearScreen", "false"];

const child = process.platform === "win32"
  ? spawn(`${npmCommand} ${npmArgs.join(" ")}`, {
    cwd: frontendDir,
    env: {
      ...process.env,
      ...runtimeEnv,
      NO_COLOR: "1",
      FORCE_COLOR: "0",
    },
    shell: true,
    stdio: ["inherit", "pipe", "pipe"],
  })
  : spawn(npmCommand, npmArgs, {
    cwd: frontendDir,
    env: {
      ...process.env,
      ...runtimeEnv,
      NO_COLOR: "1",
      FORCE_COLOR: "0",
    },
    stdio: ["inherit", "pipe", "pipe"],
  });

child.stdout.on("data", (chunk) => process.stdout.write(chunk));
child.stderr.on("data", (chunk) => process.stderr.write(chunk));
child.on("exit", (code) => process.exit(code ?? 0));

process.on("SIGINT", () => child.kill("SIGINT"));
process.on("SIGTERM", () => child.kill("SIGTERM"));

function readRuntimeEnv(path) {
  if (!existsSync(path)) return {};
  const values = {};
  for (const rawLine of readFileSync(path, "utf8").split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const index = line.indexOf("=");
    values[line.slice(0, index).trim()] = line.slice(index + 1).trim();
  }
  return values;
}
