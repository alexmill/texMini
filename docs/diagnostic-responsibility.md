# Diagnostic Responsibility

## Principle

texMini provisions the managed toolchain and runs the document's declared build. texMini does not repair the document.

texMini may automatically change only the TinyTeX runtime that texMini manages. Automatic recovery may install a TeX Live package or build tool when authoritative TeX Live metadata identifies that package as a missing part of the declared build.

texMini must not change project inputs or silently change build intent. A possible fix is outside texMini's scope when the fix would edit a source file, select a different engine, enable a security-sensitive option, substitute content, or reinterpret a package's behavior.

This boundary is part of the product design. LaTeX has many engines, packages, templates, build tools, and extension points. Many document problems have deterministic fixes, but deterministic fixability does not make those problems texMini's responsibility.

## Responsibility Boundary

texMini owns:

- Installing and locating its managed TinyTeX runtime.
- Finding supported TeX Live files and tools required by the project's declared build.
- Mapping a missing managed-runtime artifact to a TeX Live package through authoritative package metadata.
- Installing known packages into the managed runtime and retrying the same build.
- Reporting package-resolution and package-installation failures.
- Invoking `latexmk` with stable noninteractive settings and the user's selected options.
- Preserving subprocess status, logs, auxiliary evidence, and changed PDF state.
- Fixing defects in texMini's orchestration, reporting, runtime management, and cleanup.

The project and the TeX ecosystem own:

- LaTeX syntax and macro errors.
- Missing project files, including document inputs, bibliographies, local classes, and local styles.
- Package-specific validation, configuration, and option errors.
- Document-class and publisher-template requirements.
- Engine compatibility and engine selection beyond the project's declared choice.
- Typesetting, layout, font selection, and content problems.
- Bibliography, citation, reference, index, and glossary correctness after the required tools and files are available.
- Any failure that cannot be resolved by provisioning the managed TinyTeX runtime without changing build intent.

## State-Ownership Rule

Automatic recovery is allowed only when all four conditions hold:

1. The missing artifact belongs to the texMini-managed toolchain.
2. Authoritative TeX Live metadata maps the artifact to one installable package or tool.
3. The action mutates only the managed runtime.
4. The retry preserves the project's files, declared engine, options, permissions, and document semantics.

If any condition does not hold, texMini must stop automatic recovery and surface the TeX failure. An unmapped or unrecognized failure is an ordinary TeX failure; it is not a request to add another diagnostic special case.

If ownership is ambiguous, texMini must treat the artifact as project-owned and pass through the failure. A package name match alone does not justify replacing a missing local file with a TeX Live package.

Missing-file detection is allowed to be incomplete. When texMini does not recognize a provisioning signal, the safe fallback is the original TeX diagnostic and complete log. texMini must not speculate about the cause.

## Prohibited Automatic Actions

texMini must not automatically:

- Edit `.tex`, `.bib`, configuration, class, style, or other project files.
- Insert packages, commands, citations, labels, or document content.
- Try different TeX engines until one succeeds.
- Enable shell escape or another security-sensitive permission.
- Replace fonts, images, bibliography data, or missing local inputs.
- Change package options or document-class options.
- Install operating-system packages or modify system configuration.
- Interpret a package-specific error as instructions for changing the document.

texMini may tell the user that an explicit external requirement or option is needed. The user decides whether to change the project, command, permissions, system, or environment.

## Responsible Diagnostic Output

For an ordinary TeX failure, texMini should provide:

- Clear attribution that TeX or `latexmk` reported the failure.
- The diagnostic text without changing its meaning.
- The source file and line when TeX supplies them.
- The complete log path.
- The underlying subprocess status for failed builds.
- A note when the failed invocation created or changed a PDF.
- Access to the complete process transcript through `--verbose`.

For example:

```text
TeX failed while compiling paper.tex.

TeX reported:
paper.tex:42: Undefined control sequence.

Full log: paper.log
Run with --verbose to show the complete TeX output.
```

texMini should not replace that evidence with a guessed explanation or package-specific repair advice.

When texMini provisions the managed runtime, texMini should state its action separately from the TeX diagnostic:

```text
TeX reported that geometry.sty was missing from the managed runtime.
texMini installed the geometry package and retried the same build.
```

## Examples at the Boundary

| Condition | texMini behavior |
| --- | --- |
| A declared TeX Live package is absent from TinyTeX | Install the mapped package and retry the same build. |
| An installed package needs another mapped TeX Live runtime file | Install the mapped dependency and retry the same build. |
| Biber or MakeIndex is required but absent from TinyTeX | Install the corresponding TeX Live tool. |
| A local document, bibliography, class, or style file is missing | Surface the TeX diagnostic without searching for a substitute. |
| An undefined command might be fixed by adding a package | Surface the TeX diagnostic without editing the source. |
| Another engine might compile the document | Surface the failure without trying other engines. |
| `minted` requires shell escape | Require an explicit user option; never enable it automatically. |
| An operating-system font or executable is missing | State the external requirement without installing or substituting it. |
| A package rejects its options or configuration | Surface the package diagnostic without interpreting it. |

## Output-Integrity Policy

TeX can produce a PDF and return success while also reporting missing characters or unresolved citations or references. texMini treats the existing set of canonical content-loss warnings as an incomplete build and exits with a nonzero status.

This behavior is a small, closed output-integrity policy. texMini does not attempt a document repair. texMini must show the warning that TeX produced and state that the policy caused the nonzero result. texMini must not diagnose the document or expand the policy for unrelated warnings without a separate product decision.

## Development Review

Before adding automatic recovery, diagnostic parsing, classification, or advice, answer these questions:

1. Does the missing artifact belong to the texMini-managed toolchain?
2. Does authoritative TeX Live metadata identify one package or tool?
3. Will the action mutate only the managed runtime?
4. Will the action preserve project files and declared build intent?
5. Will texMini preserve the original TeX evidence and attribution?

Automatic recovery requires a yes answer to every question. Otherwise, prefer transparent pass-through output.

Tests should enforce the boundary instead of cataloguing LaTeX errors. Contract tests should verify that:

- texMini mutates only the managed runtime during automatic recovery.
- texMini retries the same declared build after provisioning.
- TeX diagnostic text keeps its attribution and meaning.
- Source locations are shown when TeX provides them.
- Failed builds identify the complete log.
- `--verbose` exposes the complete tool output.
- Unrecognized failures cause no speculative advice or additional mutation.
- Recovery stops when installation fails or a retry makes no progress.

Do not add a parser and test for each new LaTeX error. A new error message from TeX is evidence to surface, not automatically a new responsibility for texMini.
