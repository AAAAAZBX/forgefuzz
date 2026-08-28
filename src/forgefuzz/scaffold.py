from __future__ import annotations

import re
from importlib import resources
from pathlib import Path


def _identifier(value: str) -> str:
    result = re.sub(r"[^a-zA-Z0-9_]", "_", value.replace("-", "_")).lower()
    if not result or result[0].isdigit():
        result = f"adapter_{result}"
    return result


def create_adapter_project(destination: Path, adapter_name: str) -> Path:
    """Create a standalone, installable example adapter project."""
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"destination is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    package_name = _identifier(destination.name)
    class_name = "".join(part.capitalize() for part in _identifier(adapter_name).split("_")) + "Adapter"
    substitutions = {
        "__PROJECT_NAME__": destination.name,
        "__PACKAGE_NAME__": package_name,
        "__ADAPTER_NAME__": adapter_name,
        "__ADAPTER_CLASS__": class_name,
    }
    template_root = resources.files("forgefuzz").joinpath("templates/adapter_project")
    def files_below(root):
        for child in root.iterdir():
            if child.is_dir():
                yield from files_below(child)
            else:
                yield child

    for source in files_below(template_root):
        if not source.is_file():
            continue
        relative = Path(str(source.relative_to(template_root)).replace("package_name", package_name))
        if relative.name.endswith(".tmpl"):
            relative = relative.with_name(relative.name[:-5])
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        content = source.read_text(encoding="utf-8")
        for old, new in substitutions.items():
            content = content.replace(old, new)
        target.write_text(content, encoding="utf-8")
    return destination
