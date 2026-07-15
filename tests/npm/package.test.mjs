import assert from "node:assert/strict";
import { chmodSync, mkdirSync, readFileSync, readdirSync, symlinkSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

const packageJson = JSON.parse(readFileSync(new URL("../../package.json", import.meta.url), "utf8"));
const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";

test("npm package exposes one Node-native executable without lifecycle downloads", () => {
  assert.deepEqual(packageJson.bin, { texmini: "npm/texmini.mjs" });
  assert.equal(packageJson.engines.node, ">=20");
  assert.deepEqual(packageJson.dependencies, { tar: "^7.5.20", "xz-decompress": "^0.2.3" });
  for (const lifecycle of ["preinstall", "install", "postinstall", "prepare"]) {
    assert.equal(packageJson.scripts[lifecycle], undefined);
  }
});

test("npm artifact contains only the launcher and required metadata", () => {
  const result = spawnSync(npmCommand, ["pack", "--dry-run", "--json"], {
    encoding: "utf8",
    shell: process.platform === "win32",
  });
  assert.equal(result.status, 0, result.stderr);
  const report = JSON.parse(result.stdout)[0];
  const files = report.files.map((entry) => entry.path).sort();
  assert.deepEqual(files, ["LICENSE", "README.md", "npm/texmini.mjs", "package.json"]);
});

test("package versions stay synchronized", () => {
  const pythonVersion = readFileSync(new URL("../../src/texmini/__init__.py", import.meta.url), "utf8");
  const nodeLauncher = readFileSync(new URL("../../npm/texmini.mjs", import.meta.url), "utf8");
  const pyproject = readFileSync(new URL("../../pyproject.toml", import.meta.url), "utf8");
  const formula = readFileSync(new URL("../../Formula/texmini.rb", import.meta.url), "utf8");
  const flake = readFileSync(new URL("../../flake.nix", import.meta.url), "utf8");
  assert.match(pythonVersion, new RegExp(`__version__ = ["']${packageJson.version}["']`));
  assert.match(nodeLauncher, new RegExp(`VERSION = ["']${packageJson.version}["']`));
  assert.match(pyproject, new RegExp(`version = ["']${packageJson.version}["']`));
  assert.match(formula, new RegExp(`version ["']${packageJson.version}["']`));
  assert.match(flake, new RegExp(`version = ["']${packageJson.version}["']`));
});

test("npm-style executable symlinks enter the CLI", { skip: process.platform === "win32" }, async (t) => {
  const directory = await mkdtemp(join(tmpdir(), "texmini-node-link-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const launcher = new URL("../../npm/texmini.mjs", import.meta.url);
  const link = join(directory, "texmini");
  chmodSync(launcher, 0o755);
  symlinkSync(launcher, link);

  const result = spawnSync(link, ["--version"], { encoding: "utf8" });

  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout.trim(), packageJson.version);
});

test("packed artifact installs into an isolated global prefix", async (t) => {
  const directory = await mkdtemp(join(tmpdir(), "texmini-node-package-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const pack = join(directory, "pack");
  const prefix = join(directory, "prefix");
  const cache = join(directory, "cache");
  mkdirSync(pack);
  const packResult = spawnSync(npmCommand, ["pack", "--pack-destination", pack], {
    encoding: "utf8",
    shell: process.platform === "win32",
  });
  assert.equal(packResult.status, 0, packResult.stderr);
  const tarball = join(pack, readdirSync(pack).find((entry) => entry.endsWith(".tgz")));
  const install = spawnSync(npmCommand, ["install", "--global", "--prefix", prefix, "--cache", cache, tarball], {
    encoding: "utf8",
    shell: process.platform === "win32",
  });
  assert.equal(install.status, 0, install.stderr);

  const binary = process.platform === "win32" ? join(prefix, "texmini.cmd") : join(prefix, "bin", "texmini");
  const result = spawnSync(binary, ["--version"], { encoding: "utf8", shell: process.platform === "win32" });

  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout.trim(), packageJson.version);
});
