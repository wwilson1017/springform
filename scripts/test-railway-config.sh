#!/usr/bin/env bash
# Exercise the real IaC program against a synthetic graph; never call the Railway CLI.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
root=$(mktemp -d)
trap 'rm -rf "$root"' EXIT
export RAILWAY_TEST_ROOT="$root" RAILWAY_TEST_MODULE="$here/../.railway/railway.ts"
export PATH="$root:$PATH"
failures=0

cat >"$root/railway" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [ "$#" != 3 ] || [ "$1" != config ] || [ "$2" != pull ] || [ "$3" != --json ]; then
  echo "Unexpected fake Railway arguments" >&2
  exit 1
fi
cat "$RAILWAY_TEST_ROOT/live.json"
SH
chmod +x "$root/railway"
cat >"$root/live.json" <<'JSON'
{
  "project": {"name": "springform"},
  "resources": [
    {
      "address": "service.web",
      "source": {"repo": "example/springform", "branch": "master"},
      "variables": {"SECRET_KEY": {"type": "preserve"}, "ENCRYPTION_KEY": {"type": "preserve"}},
      "build": {"builder": "RAILPACK", "watchPatterns": ["/**"]},
      "deploy": {"drainingSeconds": 15},
      "volumeAttachments": {"data": {"volume": "volume.web-volume", "mountPath": "/data"}}
    },
    {"address": "service.other", "variables": {"SECRET_KEY": {"type": "preserve"}}},
    {"address": "volume.web-volume", "name": "web-volume"},
    {"address": "volume.other-volume", "name": "other-volume"}
  ]
}
JSON

# Each case imports in a fresh process: SPRINGFORM_SERVICE is read at import time.
check() {
  local case_name=$1 what=$2 out
  if out=$(node --experimental-strip-types --input-type=module -e '
    import assert from "node:assert/strict";
    import { readFileSync, writeFileSync } from "node:fs";
    import { pathToFileURL } from "node:url";
    const caseName = process.argv[1];
    const root = process.env.RAILWAY_TEST_ROOT;
    const livePath = `${root}/live.json`;
    const live = JSON.parse(readFileSync(livePath, "utf8"));
    const project = (name, def) => ({ name, ...def });
    process.env.SPRINGFORM_SERVICE = caseName === "missing" ? "missing" : "web";
    if (caseName === "unset") delete process.env.SPRINGFORM_SERVICE;
    const evaluate = async () => {
      const module = await import(pathToFileURL(process.env.RAILWAY_TEST_MODULE));
      assert.equal(module.partial, process.env.SPRINGFORM_SERVICE);
      return module.default({ projectName: caseName === "wrong-project" ? "other" : "springform" }, project);
    };
    const errors = {
      unset: "Set SPRINGFORM_SERVICE to the Railway service that runs Springform.",
      missing: "No service named missing in the linked Railway project.",
      "wrong-project": "railway config pull read project springform, not other.",
    };
    if (errors[caseName]) {
      await assert.rejects(evaluate, { message: errors[caseName] });
    } else if (caseName === "overlay") {
      const result = await evaluate();
      const expected = structuredClone(live.resources[0]);
      expected.build = { ...expected.build, builder: "DOCKERFILE", dockerfilePath: "Dockerfile" };
      expected.deploy = {
        ...expected.deploy,
        healthcheckPath: "/up", healthcheckTimeout: 60, restartPolicyMaxRetries: 3,
      };
      assert.deepEqual(result, {
        name: "springform", resources: [expected, live.resources[2]],
      });
      writeFileSync(`${root}/result.json`, JSON.stringify(result));
    } else if (caseName === "idempotent") {
      const first = JSON.parse(readFileSync(`${root}/result.json`, "utf8"));
      live.resources[0] = first.resources[0];
      writeFileSync(livePath, JSON.stringify(live));
      assert.deepEqual(await evaluate(), first);
    } else if (caseName === "restart") {
      live.resources[0].deploy.restartPolicyType = "NEVER";
      writeFileSync(livePath, JSON.stringify(live));
      assert.equal((await evaluate()).resources[0].deploy.restartPolicyType, "ON_FAILURE");
    } else {
      throw new Error(`Unknown case ${caseName}`);
    }
  ' "$case_name" 2>&1); then
    echo "ok    $what"
  else
    echo "FAIL  $what"
    printf '      %s\n' "${out//$'\n'/$'\n'      }"
    failures=$((failures + 1))
  fi
}

check overlay "only Springform settings change; source, variables and attached volume survive"
check idempotent "applying the overlay twice gives the same graph"
check unset "unset SPRINGFORM_SERVICE fails plainly"
check missing "missing service fails plainly"
check wrong-project "a different project fails plainly"
check restart "a pulled non-default restart policy goes back to ON_FAILURE"

if [ "$failures" -gt 0 ]; then
  echo "$failures case(s) failed"
  exit 1
fi
echo "All Railway config cases behave."
