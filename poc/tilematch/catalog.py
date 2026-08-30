"""Walk the reference tree and derive Product / Face / Code metadata.

The source tree is a Google Drive export with real inconsistencies, so this
validates rather than assumes (per CLAUDE.md). Every file that cannot be parsed
or read is reported, never silently dropped.

Domain vocabulary (these are not interchangeable):
    Size    - parent folder, e.g. "45X90"
    Design  - child folder, e.g. "CREMA MARMOL"
    Product - a size + design pair; the unit of identity
    Face    - one manufactured surface variation within a product
    Code    - the cleaned file name; this IS the answer a scan returns
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}

COPY_PREFIX = re.compile(r"^copy\s+of\s+", re.IGNORECASE)

# A folder whose name carries no design information. Its contents stay indexed
# (they are real tiles) but the design is recorded as unknown and flagged.
UNNAMED_DESIGN_RE = re.compile(r"^(untitled|new)\s+folder\s*\d*$", re.IGNORECASE)
UNKNOWN_DESIGN = "UNKNOWN"


def normalize_folder(name: str) -> str:
    """Whitespace- and case-normalize a size/design folder name.

    Matches the architecture's create-if-missing lookup convention, and is what
    keeps "45X90/ SYLVORA", "30X90/ARKE " and "40X40/IMPERIAL " from becoming
    distinct products from their clean-named siblings.
    """
    return re.sub(r"\s+", " ", name).strip().upper()


def clean_code(filename: str) -> str:
    """File name -> the Code shown to staff.

    Strips the conditional "Copy of " prefix (only 95 of 133 files carry it) and
    the extension. Handles the double-dot case
    "RP.HTC.0001DC.MA.0T..jpg" -> "RP.HTC.0001DC.MA.0T", which a naive
    rsplit('.', 1) leaves a trailing dot on, and trailing spaces before the
    extension ("279 .jpg" -> "279").
    """
    stem = Path(filename).stem
    stem = COPY_PREFIX.sub("", stem)
    return stem.strip().strip(".").strip()


# Five naming conventions coexist in this tree. Face extraction tries each in
# the order most-specific-first, and returns None rather than guessing.
FACE_PATTERNS = (
    re.compile(r"^RP\.[A-Z]{3}\.(\d{3,4})[A-Z]{2}\.", re.IGNORECASE),  # RP.CMA.0001DJ.SM.0T
    re.compile(r"_F(\d+)$", re.IGNORECASE),                            # 11DH.MA_F1
    re.compile(r"^(\d+)$"),                                            # 146, 279
    re.compile(r"^(\d+)[A-Z]{1,3}\b", re.IGNORECASE),                  # 1Jk, 61M, 11SP, 7BG ...
)


def extract_face(code: str) -> str | None:
    for pat in FACE_PATTERNS:
        m = pat.search(code)
        if m:
            return m.group(1).lstrip("0") or "0"
    return None


@dataclass
class Reference:
    """One reference image: the unit that a scan returns."""

    path: Path
    relpath: str
    size: str
    design: str
    code: str
    face: str | None
    design_unknown: bool = False

    @property
    def product(self) -> str:
        """size + design — the granularity accuracy is scored at (PRD OQ-12)."""
        return f"{self.size} / {self.design}"

    def as_dict(self) -> dict:
        return {
            "relpath": self.relpath,
            "size": self.size,
            "design": self.design,
            "code": self.code,
            "face": self.face,
            "product": self.product,
            "design_unknown": self.design_unknown,
        }


@dataclass
class ScanReport:
    """Everything the walk found, including what it refused to index."""

    references: list[Reference] = field(default_factory=list)
    skipped_unreadable: list[tuple[str, str]] = field(default_factory=list)
    skipped_non_image: list[str] = field(default_factory=list)
    unnamed_design: list[str] = field(default_factory=list)
    normalized_folders: set[str] = field(default_factory=set)
    no_face: list[str] = field(default_factory=list)
    unexpected_depth: list[str] = field(default_factory=list)

    @property
    def products(self) -> set[str]:
        return {r.product for r in self.references}


def scan_tree(root: Path) -> ScanReport:
    """Walk <root>/<SIZE>/<DESIGN>/<file> and build the reference list.

    Depth is not uniform in the real Drive tree, so anything that is not exactly
    two levels deep is recorded in `unexpected_depth` for a human to look at
    rather than being force-fitted into the size/design model.
    """
    root = Path(root)
    report = ScanReport()

    for path in sorted(root.rglob("*")):
        if path.is_dir() or path.name.startswith("."):
            continue

        rel = path.relative_to(root)
        parts = rel.parts

        if path.suffix.lower() not in IMAGE_SUFFIXES:
            report.skipped_non_image.append(str(rel))
            continue

        if len(parts) != 3:
            report.unexpected_depth.append(str(rel))
            continue

        # Zero-byte and truncated files are real in this tree (two in "30X90/ARKE ").
        # Catch them here so a bad file can never abort an index build.
        if path.stat().st_size == 0:
            report.skipped_unreadable.append((str(rel), "zero-byte file"))
            continue

        raw_size, raw_design, filename = parts
        size = normalize_folder(raw_size)
        design = normalize_folder(raw_design)

        if raw_size != size or raw_design != design:
            report.normalized_folders.add(f"{raw_size}/{raw_design}")

        design_unknown = bool(UNNAMED_DESIGN_RE.match(raw_design.strip()))
        if design_unknown:
            design = UNKNOWN_DESIGN
            report.unnamed_design.append(str(rel))

        code = clean_code(filename)
        face = extract_face(code)
        if face is None:
            report.no_face.append(str(rel))

        report.references.append(
            Reference(
                path=path,
                relpath=str(rel),
                size=size,
                design=design,
                code=code,
                face=face,
                design_unknown=design_unknown,
            )
        )

    return report


def format_report(report: ScanReport) -> str:
    n_vec_note = ""
    lines = [
        "ingest report",
        "─" * 62,
        f"  indexed        {len(report.references):5d}  images / {len(report.products)} products{n_vec_note}",
    ]
    if report.skipped_unreadable:
        lines.append(f"  skipped        {len(report.skipped_unreadable):5d}  unreadable")
        for rel, why in report.skipped_unreadable:
            lines.append(f"                        {rel}  ({why})")
    if report.skipped_non_image:
        lines.append(f"  skipped        {len(report.skipped_non_image):5d}  non-image files")
    if report.unnamed_design:
        lines.append(
            f"  ⚠ unnamed design {len(report.unnamed_design):3d}  → design {UNKNOWN_DESIGN}, needs classification"
        )
        codes = sorted({clean_code(Path(r).name) for r in report.unnamed_design})
        lines.append(f"                        {', '.join(codes)}")
    if report.normalized_folders:
        lines.append(f"  ⚠ whitespace     {len(report.normalized_folders):3d}  folder names normalized")
        for f in sorted(report.normalized_folders):
            lines.append(f"                        {f!r}")
    if report.no_face:
        lines.append(f"  ⚠ no face number {len(report.no_face):3d}  code kept, face left null")
    if report.unexpected_depth:
        lines.append(f"  ⚠ unexpected depth {len(report.unexpected_depth):3d}  not <size>/<design>/<file>")
        for f in report.unexpected_depth[:10]:
            lines.append(f"                        {f}")
    lines.append("─" * 62)
    return "\n".join(lines)
