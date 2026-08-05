import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(scriptDirectory, "..", "..");
const require = createRequire(path.join(root, "frontend", "package.json"));
const { chromium } = require("playwright");
const python = path.join(root, ".venv", "Scripts", "python.exe");
const temporary = await mkdtemp(path.join(os.tmpdir(), "catalyst-e2e-"));
const data = path.join(temporary, "data");
const activeChildren = new Set();

async function freePort() {
  return await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() => resolve(port));
    });
  });
}

async function waitForRuntime(runtime) {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    try {
      const value = JSON.parse(await readFile(runtime, "utf8"));
      const health = await fetch(`${value.origin}/api/health`);
      if (health.ok) return value;
    } catch {
      // The server is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("E2E backend did not become ready");
}

async function startBackend(runNumber) {
  const port = await freePort();
  const runtime = path.join(temporary, `runtime-${runNumber}.json`);
  const pythonPath = [path.join(root, "backend"), process.env.PYTHONPATH]
    .filter(Boolean)
    .join(path.delimiter);
  const child = spawn(python, [
    path.join(root, "tests", "e2e", "server.py"),
    "--port", String(port),
    "--data", data,
    "--runtime", runtime,
  ], {
    cwd: root,
    env: { ...process.env, PYTHONPATH: pythonPath },
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });
  activeChildren.add(child);
  child.once("exit", () => activeChildren.delete(child));
  let errors = "";
  child.stderr.on("data", (chunk) => { errors += chunk.toString(); });
  try {
    const state = await waitForRuntime(runtime);
    return { child, state };
  } catch (error) {
    child.kill();
    throw new Error(`${error instanceof Error ? error.message : error}\n${errors}`);
  }
}

async function stopBackend(child) {
  child.kill();
  await new Promise((resolve) => {
    if (child.exitCode !== null) resolve();
    else child.once("exit", resolve);
  });
  activeChildren.delete(child);
}

const browser = await chromium.launch({ channel: "msedge", headless: true });
try {
  const first = await startBackend(1);
  const firstPage = await browser.newPage();
  await firstPage.goto(`${first.state.origin}/launch?token=${encodeURIComponent(first.state.launch_token)}`);
  await firstPage.getByRole("link", { name: "⌕ 检索", exact: true }).click();
  await firstPage.getByPlaceholder("输入关键词、题名、作者或 DOI").fill("photocatalysis");
  await firstPage.getByRole("button", { name: "检索", exact: true }).click();
  await firstPage.getByRole("button", { name: "Visible light photocatalysis for carbon dioxide conversion" }).waitFor();
  await firstPage.getByRole("button", { name: "加入知识库" }).click();
  await firstPage.getByText("已加入知识库").waitFor();
  await firstPage.close();
  await stopBackend(first.child);

  const second = await startBackend(2);
  const secondPage = await browser.newPage();
  await secondPage.goto(`${second.state.origin}/launch?token=${encodeURIComponent(second.state.launch_token)}`);
  await secondPage.getByRole("link", { name: "知识库" }).click();
  await secondPage.getByRole("heading", { name: "Visible light photocatalysis for carbon dioxide conversion" }).waitFor();
  await secondPage.close();
  await stopBackend(second.child);
  process.stdout.write("E2E passed: search, save, backend restart, and persistent library.\n");
} finally {
  for (const child of activeChildren) child.kill();
  await Promise.all([...activeChildren].map((child) => new Promise((resolve) => {
    if (child.exitCode !== null) resolve();
    else child.once("exit", resolve);
  })));
  await browser.close();
  await rm(temporary, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}
