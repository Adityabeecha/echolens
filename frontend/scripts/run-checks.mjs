// Runs every frontend check that needs no browser or server, in CI and locally
// (`npm run check`). Before this, CI only built the app, so these scripts ran
// only when someone remembered to.
//
// verify-login-overflow.mjs is left out: it drives a real browser on a debug
// port and skips itself when none is listening.
import { spawnSync } from "node:child_process";
import { readdirSync } from "node:fs";

const BROWSER_ONLY = new Set(["verify-login-overflow.mjs"]);

const verify = readdirSync("scripts")
  .filter((f) => f.startsWith("verify-") && f.endsWith(".mjs") && !BROWSER_ONLY.has(f))
  .map((f) => ["node", [`scripts/${f}`]]);

const unitTests = [
  "scripts/onboarding-progress.test.mjs",
  ...readdirSync("src/screens", { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .flatMap((d) => readdirSync(`src/screens/${d.name}`)
      .filter((f) => f.endsWith(".test.mjs"))
      .map((f) => `src/screens/${d.name}/${f}`)),
].map((f) => ["node", ["--experimental-strip-types", "--test", f]]);

const failed = [];
for (const [cmd, args] of [...verify, ...unitTests]) {
  const name = args[args.length - 1];
  const run = spawnSync(cmd, args, { encoding: "utf8" });
  if (run.status === 0) {
    console.log(`PASS ${name}`);
  } else {
    failed.push(name);
    console.log(`FAIL ${name}\n${run.stdout}${run.stderr}`);
  }
}

console.log(failed.length ? `\n${failed.length} check(s) failed` : "\nAll frontend checks passed");
process.exit(failed.length ? 1 : 0);
