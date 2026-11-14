/**
 * HorizonPort's reference Node adapter.
 *
 * A launcher needs three things from HorizonPort: a signed-in account, a
 * prepared build, and a game process. This adapter shows all three with no
 * dependencies, so an Electron/Tauri/Node launcher can copy what it needs:
 *
 *   - `horizonport.mjs` runs the toolkit (fetch, prepare, instance, check) and
 *     streams its `--json` events;
 *   - `auth.mjs` does the Microsoft device-code flow and writes the session
 *     JSON the game reads;
 *   - `launch.mjs` starts `horizon-client` with the Launch API's arguments,
 *     hands the session over on stdin, and explains the exit code.
 *
 * Run the demo against a project made by `horizonport init`:
 *
 *   node adapter/index.mjs setup --download --session ./session.json
 *   node adapter/index.mjs add Work
 *   node adapter/index.mjs play Work
 */

export { HorizonPort, ToolError } from "./horizonport.mjs";
export { deviceCodeSignIn, writeSession, readSession, refreshSession } from "./auth.mjs";
export { launch, plan, crashReport, EXIT_MEANINGS } from "./launch.mjs";
