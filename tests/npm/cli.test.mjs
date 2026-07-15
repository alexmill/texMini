import assert from "node:assert/strict";
import { chmodSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { mkdtemp, rm } from "node:fs/promises";
import test from "node:test";

import {
  TINYTEX_BOOTSTRAP_PACKAGES,
  bootstrapTinytex,
  ensureTinytexEngine,
  packageFromTlmgrSearch,
  parseArgs,
  resolveTinytexPackages,
  runLatexmkBackend,
  runTinytexCompile,
  runTinytexBackend,
  texLogRequirements,
  texSourceRequirements,
  tinytexPlatformKey,
  validateTinytexArchiveEntry,
} from "../../npm/texmini.mjs";

async function temporaryDirectory(t) {
  const directory = await mkdtemp(join(tmpdir(), "texmini-node-test-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  return directory;
}

function managedBin(root) {
  const bin = join(root, "bin", "test-platform");
  mkdirSync(bin, { recursive: true });
  return bin;
}

function executable(file) {
  writeFileSync(file, "#!/bin/sh\nexit 0\n", "utf8");
  chmodSync(file, 0o755);
}

test("argument parsing matches the Python defaults and environment controls", () => {
  const options = parseArgs(
    ["--backend=tinytex", "--engine", "xelatex", "--no-install", "paper.tex", "refs.bib", "-silent"],
    { TEXMINI_AUTO_CLEAN: "false" },
    "texmini",
  );

  assert.deepEqual(options, {
    backend: "tinytex",
    engine: "xelatex",
    autoClean: false,
    autoInstall: false,
    latexmkArgs: ["paper.tex", "-silent"],
    bibFiles: ["refs.bib"],
    texFile: "paper.tex",
  });
});

test("TinyTeX platform selection distinguishes glibc, musl, and ARM64", () => {
  assert.equal(tinytexPlatformKey("linux", "x64", { header: { glibcVersionRuntime: "2.39" } }), "linux-x86_64");
  assert.equal(tinytexPlatformKey("linux", "x64", { header: {} }), "linuxmusl-x86_64");
  assert.equal(tinytexPlatformKey("linux", "arm64", { header: {} }), "linux-arm64");
  assert.equal(tinytexPlatformKey("darwin", "arm64", { header: {} }), "darwin");
});

test("archive validation allows internal links and rejects paths outside TinyTeX", () => {
  assert.equal(
    validateTinytexArchiveEntry(
      "TinyTeX/bin/universal-darwin/tlmgr",
      { type: "SymbolicLink", linkpath: "../../texmf-dist/scripts/texlive/tlmgr.pl" },
    ),
    true,
  );
  assert.throws(
    () => validateTinytexArchiveEntry("TinyTeX/bin/escape", { type: "SymbolicLink", linkpath: "../../../outside" }),
    /Unsafe link/,
  );
  assert.throws(() => validateTinytexArchiveEntry("../outside", { type: "File" }), /Unsafe path/);
});

test("log parser extracts multiple package, class, bibliography, and font files", async (t) => {
  const directory = await temporaryDirectory(t);
  const log = join(directory, "paper.log");
  writeFileSync(
    log,
    [
      "! LaTeX Error: File `alpha.sty' not found.",
      "! LaTeX Error: File `report.cls' not found.",
      "I couldn't open style file plainnat.bst",
      "Package biblatex Info: Trying to load bibliography style 'custom'",
      "Package biblatex Error: Style 'custom' not found",
      "pdfTeX error: pdflatex (file tcrm1095): Font tcrm1095 at 600 not found",
      "Package biblatex Warning: Please (re)run Biber on the file:",
    ].join("\n"),
    "utf8",
  );

  const [missing, packages] = texLogRequirements(log);

  assert.deepEqual(missing, ["alpha.sty", "report.cls", "plainnat.bst", "tcrm1095.tfm", "custom.bbx"]);
  assert.deepEqual(packages, ["biber"]);
});

test("source parser extracts classes, comma-separated packages, and Biber", async (t) => {
  const directory = await temporaryDirectory(t);
  const source = join(directory, "paper.tex");
  writeFileSync(source, "\\documentclass{memoir}\n\\usepackage{geometry, xcolor}\n\\usepackage[backend=biber]{biblatex}\n", "utf8");

  assert.deepEqual(texSourceRequirements(source), [
    ["memoir.cls", "geometry.sty", "xcolor.sty", "biblatex.sty"],
    ["biber"],
  ]);
});

test("resolver uses cached mappings before tlmgr search and writes compatible JSON", async (t) => {
  const directory = await temporaryDirectory(t);
  const cache = join(directory, "package-map.json");
  writeFileSync(cache, '{"cached.sty":"cached-package"}\n', "utf8");
  const calls = [];
  const runner = (args) => {
    calls.push(args);
    return { returncode: 0, stdout: "fresh-package: texmf-dist/tex/latex/fresh/fresh.sty\n", stderr: "" };
  };

  const resolved = resolveTinytexPackages(directory, ["cached.sty", "fresh.sty"], cache, {}, runner);

  assert.deepEqual(resolved, { "cached.sty": "cached-package", "fresh.sty": "fresh-package" });
  assert.deepEqual(calls, [["tlmgr", "search", "--global", "--file", "/fresh.sty"]]);
  assert.deepEqual(JSON.parse(readFileSync(cache, "utf8")), {
    "cached.sty": "cached-package",
    "fresh.sty": "fresh-package",
  });
});

test("tlmgr search parser accepts split package and path output", () => {
  assert.equal(packageFromTlmgrSearch("package-name:\n\ttexmf-dist/tex/latex/name/file.sty\n"), "package-name");
});

test("TinyTeX-0 bootstrap updates once and installs the core in one batch", async (t) => {
  const directory = await temporaryDirectory(t);
  const root = join(directory, "TinyTeX");
  const bin = managedBin(root);
  executable(join(bin, "tlmgr"));
  const calls = [];
  const runner = (args) => {
    calls.push(args);
    if (args[1] === "install") executable(join(bin, "latexmk"));
    return { returncode: 0, stdout: "", stderr: "" };
  };

  bootstrapTinytex(root, { PATH: "" }, runner);

  assert.deepEqual(calls, [
    ["tlmgr", "update", "--self"],
    ["tlmgr", "install", ...TINYTEX_BOOTSTRAP_PACKAGES],
  ]);
});

test("XeLaTeX engine provisioning installs xetex only when the executable is absent", async (t) => {
  const directory = await temporaryDirectory(t);
  const root = join(directory, "TinyTeX");
  const bin = managedBin(root);
  executable(join(bin, "latexmk"));
  const calls = [];
  const runner = (args) => {
    calls.push(args);
    return { returncode: 0, stdout: "", stderr: "" };
  };

  ensureTinytexEngine(root, "xelatex", { PATH: bin }, runner);

  assert.deepEqual(calls, [["tlmgr", "install", "xetex"]]);
});

test("TinyTeX batches all resolved packages and retries once", async (t) => {
  const directory = await temporaryDirectory(t);
  const root = join(directory, "TinyTeX");
  const bin = managedBin(root);
  executable(join(bin, "latexmk"));
  const source = join(directory, "paper.tex");
  writeFileSync(source, "\\documentclass{article}\n\\usepackage{alpha,beta}\n", "utf8");
  writeFileSync(join(directory, "paper.log"), "! LaTeX Error: File `alpha.sty' not found.\n! LaTeX Error: File `beta.sty' not found.\n", "utf8");
  const calls = [];
  let compileCount = 0;
  const runner = (args) => {
    calls.push(args);
    if (args[0] === "latexmk") return { returncode: compileCount++ === 0 ? 1 : 0, stdout: "", stderr: "" };
    if (args[0] === "kpsewhich") return { returncode: 1, stdout: "/texmf/article.cls\n", stderr: "" };
    if (args[0] === "tlmgr" && args[1] === "search") {
      const file = args.at(-1).slice(1, -4);
      return { returncode: 0, stdout: `${file}-package: texmf-dist/tex/latex/${file}/${file}.sty\n`, stderr: "" };
    }
    return { returncode: 0, stdout: "", stderr: "" };
  };
  const env = {
    PATH: "",
    TEXMINI_TINYTEX_ROOT: root,
    TEXMINI_PACKAGE_MAP: join(directory, "package-map.json"),
  };

  const result = await runTinytexBackend("pdflatex", false, true, source, [source], env, {
    runner,
    installer: async () => {},
  });

  assert.equal(result.returncode, 0);
  assert.deepEqual(calls.filter((args) => args[0] === "tlmgr" && args[1] === "install"), [
    ["tlmgr", "install", "alpha-package", "beta-package"],
  ]);
  const compileCalls = calls.filter((args) => args[0] === "latexmk");
  assert.equal(compileCalls.length, 2);
  assert.ok(compileCalls[1].includes("-g"));
});

test("no-install prevents package resolution and retry", async (t) => {
  const directory = await temporaryDirectory(t);
  const root = join(directory, "TinyTeX");
  const bin = managedBin(root);
  executable(join(bin, "latexmk"));
  const source = join(directory, "paper.tex");
  writeFileSync(source, "\\documentclass{article}\n", "utf8");
  const calls = [];
  const runner = (args) => {
    calls.push(args);
    return { returncode: 1, stdout: "", stderr: "" };
  };

  const result = await runTinytexBackend(
    "pdflatex",
    false,
    false,
    source,
    [source],
    { PATH: "", TEXMINI_TINYTEX_ROOT: root },
    { runner, installer: async () => {} },
  );

  assert.equal(result.returncode, 1);
  assert.equal(calls.filter((args) => args[0] === "latexmk").length, 1);
  assert.equal(calls.filter((args) => args[0] === "tlmgr").length, 0);
});

test("system latexmk backend never invokes tlmgr", () => {
  const calls = [];
  runLatexmkBackend("pdflatex", ["paper.tex"], {}, (args) => {
    calls.push(args);
    return { returncode: 0, stdout: "", stderr: "" };
  });
  assert.deepEqual(calls, [["latexmk", "-pdf", "paper.tex"]]);
});

test("managed TinyTeX compile cannot stop for interactive input", () => {
  const calls = [];
  runTinytexCompile("pdflatex", ["paper.tex"], {}, false, (args) => {
    calls.push(args);
    return { returncode: 1, stdout: "", stderr: "" };
  });

  assert.deepEqual(calls, [["latexmk", "-pdf", "-interaction=nonstopmode", "paper.tex"]]);
});
