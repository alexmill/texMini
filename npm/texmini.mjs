#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { accessSync, constants, createReadStream, createWriteStream, existsSync, mkdirSync, readFileSync, readdirSync, realpathSync, renameSync, rmSync, statSync, unlinkSync, writeFileSync } from "node:fs";
import { homedir, platform, arch } from "node:os";
import { basename, dirname, extname, join, posix, resolve } from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import { fileURLToPath } from "node:url";

export const VERSION = "0.1.0";
export const DEFAULT_TINYTEX_BUNDLE = "TinyTeX-0";
export const TINYTEX_BOOTSTRAP_PACKAGES = ["latex-bin", "latexmk", "metafont", "mfware"];
export const TINYTEX_ENGINE_PACKAGES = { xelatex: "xetex" };
export const AUTO_INSTALL_RETRIES = 5;
export const TINYTEX_RELEASE_API = "https://api.github.com/repos/rstudio/tinytex-releases/releases/latest";

const ENGINE_ARGS = {
  texmini: ["-pdf"],
  latexmk: ["-pdf"],
  pdflatex: ["-pdf"],
  lualatex: ["-lualatex"],
  xelatex: ["-xelatex"],
};

const AUX_EXTENSIONS = [
  "aux",
  "bbl",
  "bcf",
  "blg",
  "fls",
  "fdb_latexmk",
  "log",
  "nav",
  "out",
  "snm",
  "toc",
  "vrb",
  "run.xml",
];

const BACKENDS = new Set(["auto", "direct", "latexmk", "tinytex"]);
const ENGINES = new Set(Object.keys(ENGINE_ARGS));
const COMMON_TEXLIVE_FILE_PACKAGES = {
  "amsmath.sty": "amsmath",
  "authoryear.bbx": "biblatex",
  "authoryear-comp.bbx": "biblatex",
  "authoryear-comp.cbx": "biblatex",
  "biblatex.sty": "biblatex",
  "csquotes.sty": "csquotes",
  "framed.sty": "framed",
  "geometry.sty": "geometry",
  "graphicx.sty": "graphics",
  "hyperref.sty": "hyperref",
  "memoir.cls": "memoir",
  "numeric.cbx": "biblatex",
  "pgf.sty": "pgf",
  "plainnat.bst": "natbib",
  "tikz.sty": "pgf",
  "unsrtnat.bst": "natbib",
  "xcolor.sty": "xcolor",
};

const MISSING_EXTENSION = "sty|cls|bst|bbx|cbx|def|fd|map|tfm|pfb|otf|ttf|enc|cfg";
const sourceCache = new Map();

export class TexMiniError extends Error {}

export function printHelp() {
  console.log(`Usage: texmini [install-tinytex] [--engine pdflatex|lualatex|xelatex|latexmk] [OPTIONS] [document.tex] [refs.bib ...]

Compile a LaTeX document, detect bibliography files, and clean auxiliary files after successful builds.

Options:
  --engine ENGINE   Select pdflatex, lualatex, xelatex, or latexmk.
  --no-clean        Keep auxiliary files after a successful build.
  --no-install      Disable TinyTeX package autoinstall.
  --version         Print the texMini version.
  -pvc              Pass latexmk continuous-preview mode and disable cleanup.

Advanced:
  --backend BACKEND Select auto, direct, latexmk, or tinytex.

All other arguments are passed through to latexmk.`);
}

export function normalizedEngine(name) {
  let command = basename(name);
  for (const suffix of ["-basic", "-biblio"]) {
    if (command.endsWith(suffix)) command = command.slice(0, -suffix.length);
  }
  return ENGINES.has(command) ? command : "texmini";
}

export function parseArgs(argv, env = process.env, executable = process.argv[1] ?? "texmini") {
  let backend = env.TEXMINI_BACKEND ?? "auto";
  let engine = normalizedEngine(env.TEXMINI_ENGINE ?? executable);
  let autoClean = (env.TEXMINI_AUTO_CLEAN ?? "true").toLowerCase() !== "false";
  let autoInstall = (env.TEXMINI_AUTO_INSTALL ?? "true").toLowerCase() !== "false";
  const latexmkArgs = [];
  const bibFiles = [];
  let texFile = null;

  for (let index = 0; index < argv.length;) {
    const argument = argv[index];
    if (argument === "--backend") {
      if (index + 1 >= argv.length) throw new TexMiniError("Error: --backend requires auto, direct, latexmk, or tinytex.");
      backend = argv[index + 1];
      index += 2;
      continue;
    }
    if (argument.startsWith("--backend=")) {
      backend = argument.slice("--backend=".length);
      index += 1;
      continue;
    }
    if (argument === "--engine") {
      if (index + 1 >= argv.length) throw new TexMiniError("Error: --engine requires pdflatex, lualatex, xelatex, or latexmk.");
      engine = argv[index + 1];
      index += 2;
      continue;
    }
    if (argument.startsWith("--engine=")) {
      engine = argument.slice("--engine=".length);
      index += 1;
      continue;
    }
    if (argument === "--no-clean") {
      autoClean = false;
      index += 1;
      continue;
    }
    if (argument === "--no-install") {
      autoInstall = false;
      index += 1;
      continue;
    }
    if (argument === "-pvc") {
      autoClean = false;
      latexmkArgs.push(argument);
      index += 1;
      continue;
    }
    if (argument.endsWith(".tex")) {
      if (texFile !== null) throw new TexMiniError(`Error: Multiple .tex files specified: ${texFile} and ${argument}`);
      texFile = argument;
      latexmkArgs.push(argument);
      index += 1;
      continue;
    }
    if (argument.endsWith(".bib")) {
      bibFiles.push(argument);
      index += 1;
      continue;
    }
    latexmkArgs.push(argument);
    index += 1;
  }

  if (!ENGINES.has(engine)) throw new TexMiniError("Error: --engine must be pdflatex, lualatex, xelatex, or latexmk.");
  if (!BACKENDS.has(backend)) throw new TexMiniError("Error: --backend must be auto, direct, latexmk, or tinytex.");
  return { backend, engine, autoClean, autoInstall, latexmkArgs, bibFiles, texFile };
}

function executableNames(command, env = process.env) {
  if (platform() !== "win32" || extname(command)) return [command];
  const extensions = (env.PATHEXT ?? ".COM;.EXE;.BAT;.CMD").split(";").filter(Boolean);
  return [command, ...extensions.map((extension) => `${command}${extension.toLowerCase()}`), ...extensions.map((extension) => `${command}${extension.toUpperCase()}`)];
}

export function executableOnPath(command, env = process.env) {
  for (const directory of (env.PATH ?? "").split(platform() === "win32" ? ";" : ":")) {
    for (const name of executableNames(command, env)) {
      const candidate = join(directory || ".", name);
      try {
        accessSync(candidate, constants.X_OK);
        if (statSync(candidate).isFile()) return candidate;
      } catch {}
    }
  }
  return null;
}

export function resolveBackend(backend, env = process.env) {
  return backend === "auto" ? (executableOnPath("latexmk", env) ? "latexmk" : "tinytex") : backend;
}

function readSourceFile(file) {
  const absolute = resolve(file);
  const stat = statSync(file);
  const cached = sourceCache.get(absolute);
  if (!cached || cached.mtimeMs !== stat.mtimeMs || cached.size !== stat.size) {
    const source = readFileSync(file, "utf8");
    sourceCache.set(absolute, { mtimeMs: stat.mtimeMs, size: stat.size, source });
    return source;
  }
  return cached.source;
}

export function detectTexFile(latexmkArgs, texFile, cwd = process.cwd()) {
  if (texFile !== null) return texFile;
  const texFiles = readdirSync(cwd, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith(".tex"))
    .map((entry) => entry.name)
    .sort();
  if (texFiles.length === 1) {
    console.log(`Auto-detected LaTeX file: ${texFiles[0]}`);
    latexmkArgs.push(texFiles[0]);
    return texFiles[0];
  }
  console.log("Error: No .tex file specified and unable to auto-detect.");
  if (texFiles.length === 0) console.log("No .tex files found in current directory.");
  else {
    console.log(`Multiple .tex files found: ${texFiles.join(" ")}`);
    console.log("Please specify which file to compile.");
  }
  throw new TexMiniError("Error: Unable to select a .tex file.");
}

export function sourceUsesBibliography(source) {
  if (source.includes("\\bibliography{") || source.includes("\\addbibresource{")) return true;
  if (!source.includes("biblatex") || !source.includes("\\usepackage")) return false;
  return /\\usepackage(?:\[[^\]]*\])?\{[^}]*\bbiblatex\b[^}]*\}/.test(source);
}

export function checkBibliography(texFile, bibFiles, cwd = process.cwd()) {
  if (!existsSync(texFile)) return;
  const source = readSourceFile(texFile);
  if (!sourceUsesBibliography(source)) return;

  console.log(`Detected bibliography usage in ${texFile}`);
  if (bibFiles.length > 0) {
    console.log(`Using explicitly specified bibliography files: ${bibFiles.join(" ")}`);
    for (const bibFile of bibFiles) {
      if (!existsSync(bibFile)) throw new TexMiniError(`Error: Specified bibliography file '${bibFile}' not found`);
      if (!source.includes(bibFile)) {
        console.log(`Warning: Bibliography file ${bibFile} specified but not referenced in ${texFile}`);
        console.log(`You may need to add \\addbibresource{${bibFile}} to your document`);
      }
    }
    return;
  }

  const detected = readdirSync(cwd, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith(".bib"))
    .map((entry) => entry.name)
    .sort();
  if (detected.length === 1) {
    console.log(`Auto-detected bibliography file: ${detected[0]}`);
    if (!source.includes(detected[0])) {
      console.log(`Warning: Bibliography file ${detected[0]} found but not referenced in ${texFile}`);
      console.log(`You may need to add \\addbibresource{${detected[0]}} to your document`);
    }
  } else if (detected.length === 0) {
    console.log(`Warning: Bibliography commands found in ${texFile} but no .bib files found`);
  } else {
    console.log(`Info: Multiple .bib files found: ${detected.join(" ")}`);
    console.log("Make sure the correct ones are referenced in your document");
    console.log(`Or specify explicitly: texmini ${texFile} file1.bib file2.bib`);
  }
}

function sourceBase(texFile) {
  const extension = extname(texFile);
  return extension ? texFile.slice(0, -extension.length) : texFile;
}

export function cleanupAuxiliaryFiles(texFile) {
  const base = sourceBase(texFile);
  for (const extension of AUX_EXTENSIONS) {
    try {
      unlinkSync(`${base}.${extension}`);
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
  }
  console.log("Build successful, all auxiliary files cleaned (kept: .tex, .bib, .pdf)");
}

export function tinytexRoot(env = process.env) {
  return env.TEXMINI_TINYTEX_ROOT ?? join(homedir(), ".texmini", "TinyTeX");
}

export function packageMapPath(env = process.env) {
  return env.TEXMINI_PACKAGE_MAP ?? join(homedir(), ".texmini", "package-map.json");
}

export function tinytexBinDir(root, executable = "latexmk", env = process.env) {
  const binRoot = join(root, "bin");
  if (existsSync(binRoot)) {
    for (const entry of readdirSync(binRoot, { withFileTypes: true }).filter((item) => item.isDirectory()).sort((a, b) => a.name.localeCompare(b.name))) {
      for (const name of executableNames(executable, env)) {
        const candidate = join(binRoot, entry.name, name);
        if (existsSync(candidate)) return join(binRoot, entry.name);
      }
    }
  }
  throw new TexMiniError(`Error: TinyTeX does not provide ${executable} at ${root}. Run: texmini install-tinytex`);
}

export function tinytexEnv(root, executable = "latexmk", env = process.env) {
  const separator = platform() === "win32" ? ";" : ":";
  return { ...env, PATH: `${tinytexBinDir(root, executable, env)}${separator}${env.PATH ?? ""}` };
}

export function tinytexBundle(env = process.env) {
  return env.TEXMINI_TINYTEX_BUNDLE ?? DEFAULT_TINYTEX_BUNDLE;
}

export function tinytexPlatformKey(platformName = platform(), architecture = arch(), report = process.report?.getReport()) {
  if (platformName === "darwin") return "darwin";
  if (platformName === "linux") {
    if (["arm64", "aarch64"].includes(architecture)) return "linux-arm64";
    if (["x64", "x86_64"].includes(architecture)) {
      return report?.header?.glibcVersionRuntime ? "linux-x86_64" : "linuxmusl-x86_64";
    }
    throw new TexMiniError(`Error: Unsupported Linux architecture: ${architecture}.`);
  }
  throw new TexMiniError("Error: The managed TinyTeX installer currently supports macOS and Linux.");
}

export function runCommand(args, { env = process.env, capture = false, quietStderr = false } = {}) {
  const result = spawnSync(args[0], args.slice(1), {
    env,
    encoding: "utf8",
    stdio: capture ? ["ignore", "pipe", quietStderr ? "ignore" : "pipe"] : "inherit",
  });
  if (result.error) {
    if (!capture) console.error(`Error: Unable to run ${args[0]}: ${result.error.message}`);
    return { returncode: 127, stdout: "", stderr: result.error.message };
  }
  return {
    returncode: result.status ?? 1,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
  };
}

export async function latestTinytexAsset(env = process.env, fetchImpl = fetch) {
  const bundle = tinytexBundle(env);
  const prefix = `${bundle}-${tinytexPlatformKey()}-`;
  const response = await fetchImpl(TINYTEX_RELEASE_API, {
    headers: { "user-agent": "texmini" },
    signal: AbortSignal.timeout(30_000),
  });
  if (!response.ok) throw new TexMiniError(`Error: TinyTeX release lookup failed with HTTP ${response.status}.`);
  const release = await response.json();
  for (const asset of release.assets ?? []) {
    if (asset.name.startsWith(prefix) && asset.name.endsWith(".tar.xz")) {
      return [asset.name, asset.browser_download_url, asset.digest ?? null];
    }
  }
  throw new TexMiniError(`Error: No ${bundle} TinyTeX archive found for this platform.`);
}

async function sha256File(file) {
  const hash = createHash("sha256");
  for await (const chunk of createReadStream(file)) hash.update(chunk);
  return hash.digest("hex");
}

async function downloadTinytexArchive(url, destination, expectedDigest, fetchImpl = fetch) {
  const response = await fetchImpl(url, {
    headers: { "user-agent": "texmini" },
    signal: AbortSignal.timeout(300_000),
  });
  if (!response.ok || !response.body) throw new TexMiniError(`Error: TinyTeX download failed with HTTP ${response.status}.`);
  await pipeline(Readable.fromWeb(response.body), createWriteStream(destination));
  if (expectedDigest?.startsWith("sha256:")) {
    const actualDigest = await sha256File(destination);
    if (actualDigest !== expectedDigest.slice("sha256:".length)) {
      throw new TexMiniError("Error: TinyTeX archive checksum verification failed.");
    }
  }
}

export function validateTinytexArchiveEntry(path, entry) {
  const normalizedPath = posix.normalize(path.replaceAll("\\", "/"));
  const isManagedPath = (candidate) => candidate === "TinyTeX" || candidate.startsWith("TinyTeX/");
  if (path.includes("\0") || posix.isAbsolute(path) || !isManagedPath(normalizedPath) || normalizedPath.includes("../")) {
    throw new TexMiniError(`Error: Unsafe path in TinyTeX archive: ${path}`);
  }
  if (entry.type === "SymbolicLink" || entry.type === "Link") {
    const linkPath = String(entry.linkpath ?? "").replaceAll("\\", "/");
    const target = entry.type === "SymbolicLink"
      ? posix.normalize(posix.join(posix.dirname(normalizedPath), linkPath))
      : posix.normalize(linkPath);
    if (posix.isAbsolute(linkPath) || !isManagedPath(target)) {
      throw new TexMiniError(`Error: Unsafe link in TinyTeX archive: ${path} -> ${linkPath}`);
    }
  }
  return true;
}

async function extractTinytexArchive(archive, destination) {
  const [{ x: extractTar }, xzModule] = await Promise.all([import("tar"), import("xz-decompress")]);
  const { XzReadableStream } = xzModule.default ?? xzModule;
  const compressed = Readable.toWeb(createReadStream(archive));
  const decompressed = new XzReadableStream(compressed);
  await pipeline(Readable.fromWeb(decompressed), extractTar({
    cwd: destination,
    filter: validateTinytexArchiveEntry,
    preservePaths: true,
    strict: true,
  }));
}

export function updateTinytexManager(root, env = process.env, runner = runCommand) {
  const managedEnv = tinytexEnv(root, "tlmgr", env);
  console.log("Updating the managed TinyTeX package manager");
  const result = runner(["tlmgr", "update", "--self"], { env: managedEnv });
  if (result.returncode !== 0) throw new TexMiniError("Error: TinyTeX package manager bootstrap failed.");
}

export function bootstrapTinytex(root, env = process.env, runner = runCommand) {
  updateTinytexManager(root, env, runner);
  const managedEnv = tinytexEnv(root, "tlmgr", env);
  console.log(`Installing TinyTeX bootstrap packages: ${TINYTEX_BOOTSTRAP_PACKAGES.join(" ")}`);
  const result = runner(["tlmgr", "install", ...TINYTEX_BOOTSTRAP_PACKAGES], { env: managedEnv });
  if (result.returncode !== 0) throw new TexMiniError("Error: TinyTeX bootstrap package installation failed.");
  tinytexBinDir(root, "latexmk", env);
}

export async function installTinytexArchive(
  root,
  env = process.env,
  { runner = runCommand, fetchImpl = fetch, assetResolver = latestTinytexAsset } = {},
) {
  if (existsSync(join(root, "bin"))) {
    if (tinytexBundle(env) === "TinyTeX-0") {
      try {
        tinytexBinDir(root, "latexmk", env);
      } catch {
        bootstrapTinytex(root, env, runner);
      }
    } else {
      tinytexBinDir(root, "latexmk", env);
    }
    console.log(`TinyTeX already installed at ${root}`);
    return;
  }

  const [name, url, digest] = await assetResolver(env, fetchImpl);
  const parent = dirname(root);
  const archive = join(parent, `.texmini-${process.pid}-${Date.now()}.tar.xz`);
  const extractionRoot = join(parent, `.texmini-extract-${process.pid}-${Date.now()}`);
  mkdirSync(parent, { recursive: true });
  mkdirSync(extractionRoot);
  console.log(`Downloading ${name}`);
  try {
    await downloadTinytexArchive(url, archive, digest, fetchImpl);
    await extractTinytexArchive(archive, extractionRoot);
    const extractedRoot = join(extractionRoot, "TinyTeX");
    if (!existsSync(extractedRoot)) throw new TexMiniError("Error: TinyTeX archive did not contain a TinyTeX runtime.");
    renameSync(extractedRoot, root);
  } finally {
    rmSync(archive, { force: true });
    rmSync(extractionRoot, { recursive: true, force: true });
  }

  if (tinytexBundle(env) === "TinyTeX-0") bootstrapTinytex(root, env, runner);
  else updateTinytexManager(root, env, runner);
  tinytexBinDir(root, "latexmk", env);
  console.log(`TinyTeX installed at ${root}`);
}

export function runLatexmkBackend(engine, latexmkArgs, env = process.env, runner = runCommand) {
  return runner(["latexmk", ...ENGINE_ARGS[engine], ...latexmkArgs], { env });
}

export function runDirectBackend(engine, texFile, latexmkArgs, env = process.env, runner = runCommand) {
  if (latexmkArgs.includes("-pvc")) {
    throw new TexMiniError("Error: direct backend does not support latexmk continuous-preview mode; use --backend latexmk.");
  }
  const selectedEngine = ["texmini", "latexmk"].includes(engine) ? "pdflatex" : engine;
  const passthrough = latexmkArgs.filter((argument) => argument !== texFile);
  return runner([selectedEngine, "-interaction=nonstopmode", "-file-line-error", ...passthrough, texFile], { env });
}

function addMissingFile(found, seen, missingFile) {
  const normalized = missingFile.includes(".") ? missingFile : `${missingFile}.tfm`;
  if (!seen.has(normalized)) {
    seen.add(normalized);
    found.push(normalized);
  }
}

export function texLogRequirements(logPath) {
  if (!existsSync(logPath)) return [[], []];
  const source = readFileSync(logPath, "utf8");
  const found = [];
  const seen = new Set();
  const patterns = [
    new RegExp(`File\\s+[` + "`'\"" + `]([^` + "`'\"" + `]+\\.(?:${MISSING_EXTENSION}))[` + "`'\"" + `]\\s+not found`, "gi"),
    new RegExp(`I\\s+(?:can't|cannot|couldn't|could not)\\s+find\\s+file\\s+[` + "`'\"" + `]?([^` + "`'\"" + `\\s]+\\.(?:${MISSING_EXTENSION}))`, "gi"),
    /I couldn't open style file\s+([^`'"\s]+\.bst)\b/gi,
    /mktextfm\s+([A-Za-z0-9_.-]+)/g,
    /Font .*?=([A-Za-z0-9_.-]+).*Metric \(TFM\) file not found/gi,
    /pdfTeX error:.*?\(file\s+([A-Za-z0-9_.-]+)\):\s+Font\b[^\n]*\bnot found/gi,
  ];
  for (const pattern of patterns) {
    for (const match of source.matchAll(pattern)) addMissingFile(found, seen, match[1]);
  }

  const contextPattern = /Package biblatex Info:\s+Trying to load (bibliography|citation) style [`'"]([^`'"]+)[`'"]/i;
  const errorPattern = /Package biblatex Error:\s+Style [`'"]([^`'"]+)[`'"]\s+not found/i;
  const biblatexContext = new Map();
  for (const line of source.split(/\r?\n/)) {
    const context = line.match(contextPattern);
    if (context) {
      biblatexContext.set(context[2], context[1].toLowerCase());
      continue;
    }
    const error = line.match(errorPattern);
    if (!error) continue;
    const style = error[1];
    const kind = biblatexContext.get(style);
    if (kind === "bibliography") addMissingFile(found, seen, `${style}.bbx`);
    else if (kind === "citation") addMissingFile(found, seen, `${style}.cbx`);
    else {
      addMissingFile(found, seen, `${style}.bbx`);
      addMissingFile(found, seen, `${style}.cbx`);
    }
  }
  const directPackages = source.includes("Package biblatex Warning:") && source.includes("Please (re)run Biber") ? ["biber"] : [];
  return [found, directPackages];
}

export function missingTexFilesFromLog(logPath) {
  return texLogRequirements(logPath)[0];
}

export function reportMissingTexFiles(texFile) {
  const missing = missingTexFilesFromLog(`${sourceBase(texFile)}.log`);
  if (missing.length > 0) console.log(`Missing TeX files found: ${missing.join(", ")}`);
}

export function texSourceRequirements(texFile) {
  if (!existsSync(texFile)) return [[], []];
  const source = readSourceFile(texFile);
  const found = [];
  const seen = new Set();
  const addFile = (name, extension) => {
    const fileName = `${name.trim()}.${extension}`;
    if (/^[A-Za-z0-9_.+-]+\.(?:sty|cls)$/.test(fileName) && !seen.has(fileName)) {
      seen.add(fileName);
      found.push(fileName);
    }
  };
  for (const match of source.matchAll(/\\documentclass(?:\[[^\]]*\])?\{([^}]+)\}/g)) addFile(match[1], "cls");
  for (const match of source.matchAll(/\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{([^}]+)\}/g)) {
    for (const packageName of match[1].split(",")) addFile(packageName, "sty");
  }
  const usesBiber = /\\usepackage(?:\[[^\]]*\])?\{[^}]*\bbiblatex\b[^}]*\}/.test(source);
  return [found, usesBiber ? ["biber"] : []];
}

export function missingTinytexSourceFiles(root, texFile, env, sourceFiles = null, runner = runCommand) {
  const files = sourceFiles ?? texSourceRequirements(texFile)[0];
  if (files.length === 0) return [];
  const result = runner(["kpsewhich", ...files], { env, capture: true, quietStderr: true });
  const found = new Set(result.stdout.split(/\r?\n/).filter(Boolean).map((line) => basename(line)));
  return files.filter((file) => !found.has(file));
}

export function loadPackageMap(file) {
  if (!existsSync(file)) return {};
  const parsed = JSON.parse(readFileSync(file, "utf8"));
  return Object.fromEntries(Object.entries(parsed).filter(([, value]) => Boolean(value)).map(([key, value]) => [String(key), String(value)]));
}

export function savePackageMap(file, packageMap) {
  mkdirSync(dirname(file), { recursive: true });
  const sorted = Object.fromEntries(Object.entries(packageMap).sort(([left], [right]) => left.localeCompare(right)));
  writeFileSync(file, `${JSON.stringify(sorted, null, 2)}\n`, "utf8");
}

export function packageFromTlmgrSearch(output) {
  let pendingPackage = null;
  for (const line of output.split(/\r?\n/)) {
    if (pendingPackage && line.includes("texmf-dist/")) return pendingPackage;
    const separator = line.indexOf(":");
    if (separator < 1) continue;
    const packageName = line.slice(0, separator);
    const rest = line.slice(separator + 1);
    if (!/^[A-Za-z0-9_.+-]+$/.test(packageName)) continue;
    if (rest.includes("texmf-dist/")) return packageName;
    if (rest.trim() === "") pendingPackage = packageName;
  }
  return null;
}

export function commonTexlivePackageForFile(fileName) {
  if (/^[et]crm\d+\.tfm$/.test(fileName)) return "ec";
  return COMMON_TEXLIVE_FILE_PACKAGES[fileName] ?? null;
}

export function resolveTinytexPackages(root, missingFiles, cachePath, env, runner = runCommand) {
  const packageMap = loadPackageMap(cachePath);
  const resolvedPackages = {};
  let updated = false;
  for (const missingFile of [...new Set(missingFiles)]) {
    if (packageMap[missingFile]) {
      resolvedPackages[missingFile] = packageMap[missingFile];
      continue;
    }
    const builtIn = commonTexlivePackageForFile(missingFile);
    if (builtIn) {
      packageMap[missingFile] = builtIn;
      resolvedPackages[missingFile] = builtIn;
      updated = true;
      continue;
    }
    const result = runner(["tlmgr", "search", "--global", "--file", `/${missingFile}`], { env, capture: true });
    const packageName = packageFromTlmgrSearch(`${result.stdout}${result.stderr}`);
    if (packageName) {
      packageMap[missingFile] = packageName;
      resolvedPackages[missingFile] = packageName;
      updated = true;
    }
  }
  if (updated) savePackageMap(cachePath, packageMap);
  return resolvedPackages;
}

export function installTinytexPackages(packages, env, runner = runCommand) {
  return runner(["tlmgr", "install", ...packages], { env });
}

export function ensureTinytexEngine(root, engine, env, runner = runCommand) {
  const selected = ["texmini", "latexmk"].includes(engine) ? "pdflatex" : engine;
  const packageName = TINYTEX_ENGINE_PACKAGES[selected];
  if (!packageName || executableOnPath(selected, env)) return;
  console.log(`Installing TeX Live engine package: ${packageName}`);
  const result = installTinytexPackages([packageName], env, runner);
  if (result.returncode !== 0) throw new TexMiniError(`Error: TinyTeX could not install the ${selected} engine.`);
}

export function runTinytexCompile(engine, latexmkArgs, env, force = false, runner = runCommand) {
  const selected = ["texmini", "latexmk"].includes(engine) ? "pdflatex" : engine;
  return runner(["latexmk", ...ENGINE_ARGS[selected], "-interaction=nonstopmode", ...(force ? ["-g"] : []), ...latexmkArgs], { env });
}

function logAutoinstallResolution(missingFiles, resolvedPackages, packages, retry) {
  console.log(`TinyTeX autoinstall retry ${retry}/${AUTO_INSTALL_RETRIES}`);
  console.log(`Missing TeX files found: ${missingFiles.length ? missingFiles.join(", ") : "none"}`);
  const pairs = Object.entries(resolvedPackages).map(([file, packageName]) => `${file} -> ${packageName}`);
  console.log(`Resolved TeX packages: ${pairs.length ? pairs.join(", ") : "none"}`);
  console.log(`Installing TeX Live packages: ${packages.length ? packages.join(" ") : "none"}`);
}

export async function runTinytexBackend(
  engine,
  autoClean,
  autoInstall,
  texFile,
  latexmkArgs,
  env = process.env,
  { runner = runCommand, installer = installTinytexArchive } = {},
) {
  if (latexmkArgs.includes("-pvc")) throw new TexMiniError("Error: TinyTeX backend does not support latexmk continuous-preview mode.");
  const root = tinytexRoot(env);
  await installer(root, env, { runner });
  const managedEnv = tinytexEnv(root, "latexmk", env);
  ensureTinytexEngine(root, engine, managedEnv, runner);
  let result = runTinytexCompile(engine, latexmkArgs, managedEnv, false, runner);
  const attemptedPackages = new Set();
  const logPath = `${sourceBase(texFile)}.log`;
  let sourceFiles = null;
  let sourceDirectPackages = [];
  let retry = 0;

  while (result.returncode !== 0 && autoInstall && retry < AUTO_INSTALL_RETRIES) {
    if (sourceFiles === null) [sourceFiles, sourceDirectPackages] = texSourceRequirements(texFile);
    const [missingFiles, logDirectPackages] = texLogRequirements(logPath);
    for (const sourceFile of missingTinytexSourceFiles(root, texFile, managedEnv, sourceFiles, runner)) {
      if (!missingFiles.includes(sourceFile)) missingFiles.push(sourceFile);
    }
    const directPackages = [...logDirectPackages, ...sourceDirectPackages];
    if (missingFiles.length === 0 && directPackages.length === 0) {
      console.log("TinyTeX autoinstall: no missing TeX files or packages found in the log or source.");
      break;
    }
    const resolvedPackages = missingFiles.length
      ? resolveTinytexPackages(root, missingFiles, packageMapPath(env), managedEnv, runner)
      : {};
    const packages = [...new Set([...Object.values(resolvedPackages), ...directPackages])]
      .filter((packageName) => !attemptedPackages.has(packageName))
      .sort();
    retry += 1;
    logAutoinstallResolution(missingFiles, resolvedPackages, packages, retry);
    if (packages.length === 0) break;

    const installResult = installTinytexPackages(packages, managedEnv, runner);
    for (const packageName of packages) attemptedPackages.add(packageName);
    if (installResult.returncode !== 0) {
      console.log("TinyTeX autoinstall: package install failed.");
      return installResult;
    }
    console.log(`TinyTeX autoinstall: retrying build (${retry}/${AUTO_INSTALL_RETRIES}).`);
    result = runTinytexCompile(engine, latexmkArgs, managedEnv, true, runner);
  }
  if (result.returncode === 0 && autoClean) cleanupAuxiliaryFiles(texFile);
  return result;
}

export async function main(argv = process.argv.slice(2), env = process.env) {
  sourceCache.clear();
  if (argv.includes("--help") || argv.includes("-h")) {
    printHelp();
    return 0;
  }
  if (argv.includes("--version")) {
    console.log(VERSION);
    return 0;
  }
  if (argv.length === 1 && argv[0] === "install-tinytex") {
    try {
      await installTinytexArchive(tinytexRoot(env), env);
      return 0;
    } catch (error) {
      console.log(error instanceof Error ? error.message : String(error));
      return 1;
    }
  }

  let options;
  let resolvedBackend;
  let detectedTexFile;
  let result;
  try {
    options = parseArgs(argv, env);
    resolvedBackend = resolveBackend(options.backend, env);
    detectedTexFile = detectTexFile(options.latexmkArgs, options.texFile);
    checkBibliography(detectedTexFile, options.bibFiles);
    if (resolvedBackend === "tinytex") {
      result = await runTinytexBackend(
        options.engine,
        options.autoClean,
        options.autoInstall,
        detectedTexFile,
        options.latexmkArgs,
        env,
      );
    } else if (resolvedBackend === "direct") {
      result = runDirectBackend(options.engine, detectedTexFile, options.latexmkArgs, env);
    } else {
      result = runLatexmkBackend(options.engine, options.latexmkArgs, env);
    }
  } catch (error) {
    console.log(error instanceof Error ? error.message : String(error));
    return 1;
  }

  if (result.returncode === 0 && options.autoClean && ["direct", "latexmk"].includes(resolvedBackend)) {
    cleanupAuxiliaryFiles(detectedTexFile);
  } else if (result.returncode !== 0) {
    reportMissingTexFiles(detectedTexFile);
    console.log("Build failed, keeping auxiliary files for debugging");
  }
  return result.returncode;
}

let invokedDirectly = false;
if (process.argv[1]) {
  try {
    invokedDirectly = realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url));
  } catch {}
}
if (invokedDirectly) process.exitCode = await main();
