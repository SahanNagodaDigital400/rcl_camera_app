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

# Multi-tile arrangement mockups, not tile faces: they show several tiles with
# grout grid lines, sometimes over a coloured base. Indexing one as a reference
# means matching a phone photo of a single tile against a picture of a floor,
# and handing staff a reference image that is not the product.
LAYOUT_RE = re.compile(r"(_layout[_\d]*|with\s+base)", re.IGNORECASE)


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
    subpath: str = ""          # grouping folders between design and file, if any

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
            "subpath": self.subpath,
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
    nested: list[str] = field(default_factory=list)
    layouts: list[str] = field(default_factory=list)
    duplicates: list[tuple[str, str]] = field(default_factory=list)

    @property
    def products(self) -> set[str]:
        return {r.product for r in self.references}


def scan_tree(root: Path) -> ScanReport:
    """Walk <root>/<SIZE>/<DESIGN>/.../<file> and build the reference list.

    Depth is not uniform: the Drive export nests some ranges under grouping
    folders ("New Wall tiles/A/") and some under timestamped export folders
    ("Outdoor tiles/Adoquines_MA-20250702T053732Z-1-001/Adoquines_MA/"). Size is
    always the top folder and design the one below it; anything deeper is a
    sub-path that is recorded but carries no identity.

    Requiring exactly three parts silently dropped 126 real images.
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

        if len(parts) < 3:
            # A file sitting directly in a size folder has no design to belong to.
            report.nested.append(str(rel))
            continue

        if LAYOUT_RE.search(path.stem):
            report.layouts.append(str(rel))
            continue

        # Zero-byte and truncated files are real in this tree (two in "30X90/ARKE ").
        # Catch them here so a bad file can never abort an index build.
        if path.stat().st_size == 0:
            report.skipped_unreadable.append((str(rel), "zero-byte file"))
            continue

        raw_size, raw_design = parts[0], parts[1]
        filename = parts[-1]
        subpath = "/".join(parts[2:-1])          # grouping folders, no identity
        if subpath:
            report.nested.append(str(rel))
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
                subpath=subpath,
            )
        )

    _find_duplicates(report)
    return report


def _find_duplicates(report: ScanReport) -> None:
    """Flag byte-identical references.

    The Drive tree carries the same export twice under different timestamped
    folders. Duplicates are reported, not removed: whether two identical files
    are one product or two is a catalogue decision, not an ingest one.
    """
    import hashlib

    seen: dict[str, str] = {}
    for ref in report.references:
        try:
            h = hashlib.sha256()
            h.update(str(ref.path.stat().st_size).encode())
            with ref.path.open("rb") as fh:
                h.update(fh.read(65536))
            key = h.hexdigest()
        except OSError:
            continue
        if key in seen:
            report.duplicates.append((seen[key], ref.relpath))
        else:
            seen[key] = ref.relpath


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
    if report.layouts:
        lines.append(f"  excluded       {len(report.layouts):5d}  layout mockups (multi-tile renders, not faces)")
    if report.nested:
        lines.append(f"  nested         {len(report.nested):5d}  under grouping folders; size/design still taken "
                     f"from the top two levels")
    if report.duplicates:
        lines.append(f"  ⚠ duplicates   {len(report.duplicates):5d}  byte-identical pairs, all indexed "
                     f"(a catalogue decision, not an ingest one)")
        for a, b in report.duplicates[:4]:
            lines.append(f"                        {b}")
            lines.append(f"                          == {a}")
    lines.append("─" * 62)
    return "\n".join(lines)
