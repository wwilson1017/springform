// Springform's Railway settings, for `railway config plan` and `railway config apply`.
// Railway never reads this file during a deploy: applying it stores the settings on the service.
// From a checkout linked (`railway link`) to the service's project and environment:
//   SPRINGFORM_SERVICE=<service> railway config plan      then the same with `apply`
// It starts from the live service (`railway config pull --json`), so the service's source,
// variables and volume stay as they are and only the settings below change.
// Left out because Railway does not store them (CLI 5.54.1): restartPolicyType, whose default is
// already ON_FAILURE, and requiredMountPath, so nothing refuses a deploy without a /data volume.
// simplification: no `railway/iac` import, so nothing to npm install. The program takes the
// `project` function the CLI passes it (the SDK's RailwayProgram type); tested with CLI 5.54.1.
import { execFileSync } from "node:child_process";

const name = process.env.SPRINGFORM_SERVICE;
if (!name) throw new Error("Set SPRINGFORM_SERVICE to the Railway service that runs Springform.");
export const partial = name;

export default (ctx, project) => {
  const live = JSON.parse(execFileSync("railway", ["config", "pull", "--json"], { encoding: "utf8" }));
  if (ctx.projectName && live.project.name !== ctx.projectName) {
    throw new Error(`railway config pull read project ${live.project.name}, not ${ctx.projectName}.`);
  }
  const svc = live.resources.find((r) => r.address === `service.${name}`);
  if (!svc) throw new Error(`No service named ${name} in the linked Railway project.`);
  const volumes = Object.values(svc.volumeAttachments ?? {}).map((a) => a.volume);
  svc.build = { ...svc.build, builder: "DOCKERFILE", dockerfilePath: "Dockerfile" };
  svc.deploy = {
    ...svc.deploy,
    healthcheckPath: "/up",
    healthcheckTimeout: 60,
    restartPolicyMaxRetries: 3,
  };
  return project(live.project.name, {
    resources: [svc, ...live.resources.filter((r) => volumes.includes(r.address))],
  });
};
