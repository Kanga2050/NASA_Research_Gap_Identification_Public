from pathlib import Path

from Servers.storage_paths import default_pdf_root, resolve_pdf_root


def _folders_in(base: Path) -> list[tuple[str, int]]:
    """(collection_name, pdf_count) for every subfolder of `base` that holds PDFs."""
    if not base.is_dir():
        return []
    out = []
    for child in sorted(base.iterdir()):
        if child.is_dir():
            out.append((child.name, len(list(child.glob("*.pdf")))))
    return out


def list_pdf_folders(storage_root: str | Path | None = None) -> str:
    """Markdown catalog of PDF *collections* the caller can chunk: their own
    uploaded folders first, then the shared public library. Pass one or more of
    these names (comma-separated) to `chunk_pdfs`."""
    lines = ["# PDF Collections Catalog\n"]

    yours = _folders_in(resolve_pdf_root(storage_root))
    lines.append("## Your collections")
    if yours:
        lines += [f"- **{name}** ({count} PDFs)" for name, count in yours]
    else:
        lines.append("_(none uploaded yet)_")

    public_base = default_pdf_root()
    # Avoid listing the public library twice if the caller's root *is* the public one.
    if resolve_pdf_root(storage_root).resolve() != public_base.resolve():
        public = _folders_in(public_base)
        lines.append("\n## Public library")
        if public:
            lines += [f"- **{name}** ({count} PDFs)" for name, count in public]
        else:
            lines.append("_(empty)_")

    return "\n".join(lines)


if __name__ == "__main__":
    print(list_pdf_folders())
