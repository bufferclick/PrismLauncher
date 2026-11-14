/**
 * Starting `horizon-client`, the way the Launch API defines it.
 *
 * The toolkit validates the command (`horizonport play --dry-run`), so a
 * launcher never guesses an option the build doesn't take. This file does the
 * part a launcher must own: hand the session over, wait, and explain the end.
 *
 *   horizon-client --resources PREPARED --game-dir GAME --home HOME \
 *                  --width 1280 --height 720 --session-stdin
 *
 * The session JSON goes to stdin and stdin is closed, so the token never
 * touches the disk or another process's command line.
 */

import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

import { HorizonPort } from "./horizonport.mjs";

export const EXIT_MEANINGS = {
  0: "the player quit",
  1: "the game stopped on an error; a crash report was saved",
  2: "the command line was refused; this is a bug in the launcher",
  101: "the game panicked; a crash report was saved",
};

const CRASH_LINE = "Horizon: crash report saved to ";

/** The crash report path in a run's stderr, when it has one. */
export function crashReport(stderr) {
  let found = null;
  for (const line of stderr.split(/\r?\n/)) {
    if (line.startsWith(CRASH_LINE)) found = line.slice(CRASH_LINE.length).trim();
  }
  return found;
}

/**
 * Ask the build what it accepts, without running the game.
 * @returns {Promise<{argv: string[], cwd: string, game: string, home: string, resources: string}>}
 */
export async function plan({ project, instance, python, width, height, fullscreen, world, server }) {
  const port = new HorizonPort({ project, python });
  return port.plan(instance, { width, height, fullscreen, world, server });
}

/**
 * Start the game and resolve with its exit code (0 is a normal quit).
 *
 * @param {object} options
 * @param {string} options.project       the port project
 * @param {string} options.instance      the instance name
 * @param {string} [options.sessionFile] a session JSON (default: `session` in the arguments)
 * @param {object} [options.session]     the session object, instead of a file
 * @param {(line: string) => void} [options.onStderr]
 */
export async function launch({
  project,
  instance,
  sessionFile,
  session,
  python,
  width,
  height,
  fullscreen,
  world,
  server,
  onStderr,
} = {}) {
  const request = await plan({ project, instance, python, width, height, fullscreen, world, server });
  const account = session ?? JSON.parse(readFileSync(sessionFile ?? path.join(project, "session.json"), "utf8"));
  for (const key of ["name", "uuid", "access_token"]) {
    if (!account[key]) throw new Error(`the session has no ${key}`);
  }
  if (!request.argv.includes("--session-stdin")) {
    throw new Error("this build does not take --session-stdin; update the build or the adapter");
  }
  return new Promise((resolve, reject) => {
    const child = spawn(request.argv[0], request.argv.slice(1), {
      cwd: request.cwd,
      env: { ...process.env, ...request.env },
      stdio: ["pipe", "inherit", "pipe"],
    });
    let stderr = "";
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
      onStderr?.(chunk.toString());
    });
    child.on("error", reject);
    child.on("close", (code) => {
      const crash = crashReport(stderr);
      if (crash) console.error(`crash report: ${crash}`);
      resolve(code ?? 1);
    });
    child.stdin.end(JSON.stringify(account) + "\n");
  });
}
