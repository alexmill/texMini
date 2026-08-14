import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


ENGINE_ARGS = {
    "pdflatex": ["-pdf"],
    "lualatex": ["-lualatex"],
    "xelatex": ["-xelatex"],
}
MAX_INSTALL_ROUNDS = 20


class TexMiniError(Exception):
    pass


class FailureKind(str, Enum):
    CEILING = "ceiling"
    DISABLED = "disabled"
    INSTALL_FAILED = "install_failed"
    ORDINARY = "ordinary"
    UNIDENTIFIED = "unidentified"
    UNMAPPED = "unmapped"


@dataclass(frozen=True)
class PrimaryError:
    message: str
    file: str | None = None
    line: int | None = None


@dataclass(frozen=True)
class CliConfig:
    engine: str | None
    clean: bool
    verbose: bool
    auto_install: bool
    watch: bool
    shell_escape: bool
    latexmk_args: list[str]
    bib_files: list[str]
    tex_file: str | None


@dataclass(frozen=True)
class BuildLayout:
    source: Path
    jobname: str
    aux_dir: Path
    out_dir: Path
    pdf_path: Path
    log_path: Path
    input_path_is_absolute: bool = False

    @classmethod
    def beside_source(cls, tex_file: str) -> "BuildLayout":
        source = Path(tex_file)
        base = source.with_suffix("")
        return cls(
            source,
            base.name,
            base.parent,
            base.parent,
            base.with_suffix(".pdf"),
            base.with_suffix(".log"),
            source.is_absolute(),
        )

    def _display_path(self, path: Path) -> str:
        if self.input_path_is_absolute:
            return os.fspath(path.resolve())
        try:
            return os.fspath(path.resolve().relative_to(Path.cwd().resolve()))
        except ValueError:
            return os.fspath(path)

    @property
    def display_pdf(self) -> str:
        return self._display_path(self.pdf_path)

    @property
    def display_log(self) -> str:
        return self._display_path(self.log_path)


@dataclass(frozen=True)
class SourceRequirements:
    files: tuple[str, ...]
    tools: tuple[str, ...]
    sources: tuple[Path, ...]
    uses_minted: bool = False


@dataclass(frozen=True)
class BuildRequest:
    engine: str
    auto_install: bool
    tex_file: str
    latexmk_args: list[str]
    started_at: float


@dataclass
class BuildOutcome:
    returncode: int
    elapsed_seconds: float
    pdf_changed: bool
    failure_kind: FailureKind | None = None
    missing_files: tuple[str, ...] = ()
    unmapped_files: tuple[str, ...] = ()
    primary_error: PrimaryError | None = None
    layout: BuildLayout | None = None

    def __post_init__(self) -> None:
        if isinstance(self.failure_kind, str):
            self.failure_kind = FailureKind(self.failure_kind)
