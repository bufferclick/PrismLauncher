/**
 * The toolkit as a library: every port action is one `horizonport` command.
 *
 * Keeping the launcher on the CLI means one implementation of the security-
 * sensitive parts (signature checks, archives, preparation, digests), and a
 * launcher written in any language can follow the same recipe. Each call
 * returns parsed JSON; failures carry the toolkit's own message.
 */

import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

export class ToolError extends Error {
  constructor(message, { code = 1, hint = "", stderr = "" } = {}) {
    super(message);
    this.name = "ToolError";
    this.code = code;
    this.hint = hint;
    this.stderr = stderr;
  }
}

/**
 * Where the toolkit lives. In a checkout it is two folders above this adapter
 * (`<repo>/porting/horizonport`); a shipped launcher bundles the kit and sets
 * HORIZONPORT to its folder.
 */
export function toolkitRoot() {
  if (process.env.HORIZONPORT) return path.resolve(process.env.HORIZONPORT);
  // Walk up from this file: a checkout has `<repo>/porting/templates/adapter-node/`,
  // a port project has `<project>/adapter/` with the kit beside it or above it.
  const here = path.dirname(fileURLToPath(import.meta.url));
  let folder = here;
  for (;;) {
    const candidate = path.join(folder, "porting", "horizonport");
    if (existsSync(candidate)) return folder;
    const parent = path.dirname(folder);
    if (parent === folder) break;
    folder = parent;
  }
  return path.resolve(here, "..", "..");
}

export class HorizonPort {
  /**
   * @param {object} options
   * @param {string} options.project  the folder holding port.config.json
   * @param {string} [options.python] the interpreter (default python3/python)
   * @param {string} [options.root]   the toolkit checkout (default: two above)
   * @param {(line: string) => void} [options.onLog]  progress messages
   */
  constructor({ project, python, root, onLog } = {}) {
    this.project = path.resolve(project ?? ".");
    this.python = python ?? (process.platform === "win32" ? "python" : "python3");
    this.root = root ?? toolkitRoot();
    this.onLog = onLog ?? (() => {});
  }

  get configFile() {
    return path.join(this.project, "port.config.json");
  }

  config() {
    if (!existsSync(this.configFile)) {
      throw new ToolError(
        `no port.config.json in ${this.project}`,
        { hint: "Run `horizonport init` first, or point the adapter at the project folder." },
      );
    }
    return JSON.parse(readFileSync(this.configFile, "utf8"));
  }

  /** Run one toolkit command; resolves with its `--json` output. */
  run(args, { timeoutMs = 0 } = {}) {
    const argv = [this.python, "-m", "porting.horizonport", "--json", "--project", this.project, ...args];
    return new Promise((resolve, reject) => {
      const child = spawn(argv[0], argv.slice(1), {
        cwd: this.root,
        env: { ...process.env, PYTHONPATH: this.root + (process.env.PYTHONPATH ? `:${process.env.PYTHONPATH}` : "") },
        stdio: ["ignore", "pipe", "pipe"],
      });
      let out = "";
      let err = "";
      const timer = timeoutMs
        ? setTimeout(() => {
            child.kill("SIGTERM");
            reject(new ToolError(`horizonport ${args[0]} timed out after ${timeoutMs} ms`));
          }, timeoutMs)
        : null;
      child.stdout.on("data", (chunk) => {
        const text = chunk.toString();
        out += text;
        for (const line of text.split(/\r?\n/)) {
          if (!line.trim()) continue;
          try {
            const event = JSON.parse(line);
            if (typeof event?.message === "string") this.onLog(event.message);
            else if (typeof event?.fraction === "number") this.onLog(`${Math.round(event.fraction * 100)}%`);
          } catch {
            this.onLog(line);
          }
        }
      });
      child.stderr.on("data", (chunk) => {
        err += chunk.toString();
        for (const line of chunk.toString().split(/\r?\n/)) {
          if (line.trim()) this.onLog(line.trimEnd());
        }
      });
      child.on("error", (error) => reject(new ToolError(String(error))));
      child.on("close", (code) => {
        if (timer) clearTimeout(timer);
        if (code !== 0) {
          const first = err.split(/\r?\n/).find((line) => line.trim()) ?? `horizonport ${args[0]} exited ${code}`;
          const hint = err.split(/\r?\n/).slice(1).join("\n").trim();
          reject(new ToolError(first.replace(/^error: /, ""), { code, hint, stderr: err }));
          return;
        }
        try {
          resolve(out.trim() ? JSON.parse(out) : {});
        } catch (error) {
          reject(new ToolError(`horizonport ${args[0]} printed something that is not JSON`, { stderr: out }));
        }
      });
    });
  }

  // -- the port's verbs ----------------------------------------------------
  doctor(full = false) {
    return this.run(["doctor", ...(full ? ["--full"] : [])]);
  }

  fetch({ tag, archive, allowUnsigned = false } = {}) {
    const args = ["fetch"];
    if (tag) args.push("--tag", tag);
    if (archive) args.push("--archive", archive);
    if (allowUnsigned) args.push("--allow-unsigned");
    return this.run(args, { timeoutMs: 30 * 60_000 });
  }

  /**
   * First-run setup, once per build: install the build if needed and prepare
   * its resources. `download` uses the owner's account to fetch the game files
   * from Mojang; `fromInstall` imports a Minecraft folder the player already
   * has. Either way every later instance reuses the result.
   */
  setup({ tag, download = false, fromInstall, session, serverJar, javaHome } = {}) {
    const args = ["prepare"];
    if (tag) args.push("--build", tag);
    if (download) args.push("--download");
    if (session) args.push("--session", session);
    if (fromInstall) args.push("--from-install", fromInstall);
    if (serverJar) args.push("--server-jar", serverJar);
    if (javaHome) args.push("--java-home", javaHome);
    return this.run(args, { timeoutMs: 60 * 60_000 });
  }

  addInstance(name, { build, noPrepare = false } = {}) {
    const args = ["instance", "new", name];
    if (build) args.push("--build", build);
    if (noPrepare) args.push("--no-prepare");
    return this.run(args, { timeoutMs: 60 * 60_000 });
  }

  instances() {
    return this.run(["instance", "list"]);
  }

  check(full = false) {
    return this.run(["check", ...(full ? ["--full"] : [])]);
  }

  /** The exact command the game will be started with, validated by the build. */
  plan(instance, options = {}) {
    const args = ["play", instance, "--dry-run"];
    if (options.width) args.push("--width", String(options.width));
    if (options.height) args.push("--height", String(options.height));
    if (options.fullscreen) args.push("--fullscreen");
    if (options.world) args.push("--world", options.world);
    if (options.server) args.push("--server", options.server);
    return this.run(args);
  }
}

// ---------------------------------------------------------------------------
// Demo CLI: `node adapter/index.mjs <command>`
// ---------------------------------------------------------------------------
if (process.argv[1] && import.meta.url === `file://${path.resolve(process.argv[1])}`) {
  const { deviceCodeSignIn, writeSession } = await import("./auth.mjs");
  const { launch } = await import("./launch.mjs");
  const [command, ...rest] = process.argv.slice(2);
  const port = new HorizonPort({
    project: process.env.HORIZONPORT_PROJECT ?? ".",
    onLog: (line) => console.error(line),
  });
  try {
    if (command === "signin") {
      const clientId = process.env.HORIZONPORT_CLIENT_ID ?? rest[0];
      const session = await deviceCodeSignIn({
        clientId,
        onCode: ({ uri, code, expiresIn }) => {
          console.log(`Open ${uri} and enter ${code} (expires in ${Math.round(expiresIn / 60)} min)`);
        },
      });
      writeSession(rest[1] ?? "./session.json", session);
      console.log(`signed in as ${session.name} (${session.uuid})`);
    } else if (command === "setup") {
      console.log(await port.setup({ download: rest.includes("--download"), session: rest[1] }));
    } else if (command === "add") {
      console.log(await port.addInstance(rest[0]));
    } else if (command === "play") {
      const code = await launch({ project: port.project, instance: rest[0], sessionFile: rest[1] });
      process.exitCode = code;
    } else if (command === "check") {
      console.log(await port.check(true));
    } else {
      console.log("usage: node adapter/index.mjs signin|setup|add|play|check");
      process.exitCode = 2;
    }
  } catch (error) {
    console.error(error instanceof Error ? `${error.name}: ${error.message}` : String(error));
    if (error?.hint) console.error(error.hint);
    process.exitCode = error?.code ?? 1;
  }
}
