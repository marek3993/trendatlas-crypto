import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const repositoryRoot = path.resolve(process.cwd(), "..");
const protectedFiles = [
  "scripts/execution/run_trendatlas_production.py",
  "deploy/systemd/mrv1-production.service",
  "deploy/systemd/mrv1-production.timer"
];

function filesUnder(directory: string): string[] {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const target = path.join(directory, entry.name);
    return entry.isDirectory() ? filesUnder(target) : [target];
  });
}

function gitDiffNames(paths: string[]): string[] {
  const output = execFileSync("git", ["diff", "--name-only", "--", ...paths], { cwd: repositoryRoot, encoding: "utf8" });
  return output.split(/\r?\n/).filter(Boolean);
}

describe("production isolation boundary", () => {
  it("keeps production execution code unreachable from the web source", () => {
    const appSource = filesUnder(path.join(process.cwd(), "src"))
      .map((file) => fs.readFileSync(file, "utf8"))
      .join("\n");
    expect(appSource).not.toMatch(/scripts\/execution|run_trendatlas_production|live[_-]?order|submit[_-]?order/i);
    expect(appSource).not.toMatch(/private[_-]?key|service[_-]?role/i);
  });

  it("does not copy a protected account address from production code", () => {
    const protectedSource = fs.readFileSync(path.join(repositoryRoot, protectedFiles[0]), "utf8");
    const addresses = protectedSource.match(/0x[a-fA-F0-9]{40}/g) ?? [];
    const appSource = filesUnder(path.join(process.cwd(), "src"))
      .map((file) => fs.readFileSync(file, "utf8"))
      .join("\n");
    addresses.forEach((address) => expect(appSource).not.toContain(address));
  });

  it("leaves protected production files unchanged", () => {
    expect(gitDiffNames(protectedFiles)).toEqual([]);
  });

  it("does not change generated data or outputs", () => {
    expect(gitDiffNames(["data", "outputs"])).toEqual([]);
  });
});
