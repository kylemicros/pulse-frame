import ast
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from tests.architecture.allowed_imports import (
    ALLOWED_IMPORTS,
    PACKAGES,
    THIRD_PARTY_HOMES,
)

DATA_MODULE = "backend/tests/architecture/allowed_imports.py"

type Found = tuple[str, tuple[str, ...], str]


@dataclass(frozen=True)
class ImportViolation:
    path: str
    line: int
    statement: str
    rule: str
    allowed: tuple[str, ...]
    detail: str

    @property
    def message(self) -> str:
        return (
            f"{self.path}:{self.line}: `{self.statement}` "
            f"breaks the {self.rule} rule: {self.detail}"
        )


@dataclass(frozen=True)
class Target:
    package: str | None
    not_a_package: str | None = None


def named(names: tuple[str, ...]) -> str:
    return ", ".join(f"`{name}`" for name in names)


def project_targets(
    node: ast.Import | ast.ImportFrom, project: str
) -> Iterator[Target]:
    if isinstance(node, ast.ImportFrom) and node.module == project:
        for alias in node.names:
            if alias.name in PACKAGES:
                yield Target(alias.name)
            else:
                yield Target(None, alias.name)
        return
    if isinstance(node, ast.Import):
        dotted = [alias.name for alias in node.names]
    else:
        dotted = [node.module or ""]
    for name in dotted:
        parts = name.split(".")
        if parts[0] == project:
            yield Target(parts[1] if len(parts) > 1 else None)


def top_level_names(node: ast.Import | ast.ImportFrom) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name.split(".")[0] for alias in node.names]
    return [(node.module or "").split(".")[0]]


def root_module_violation(project: str, target: str) -> Found:
    return (
        "layering",
        (),
        f"the `{project}` root module may import no project package, "
        f"not `{target}`. Move the code into the package that uses it.",
    )


def root_import_violation(
    package: str, allowed: tuple[str, ...], target: Target, project: str
) -> Found:
    may = f"only {named(allowed)}" if allowed else "no project package"
    why = (
        f"`{target.not_a_package}` is not a package, so "
        if target.not_a_package
        else ""
    )
    return (
        "layering",
        allowed,
        f"`{package}` may import {may} besides itself "
        f'(`ALLOWED_IMPORTS["{package}"]` in {DATA_MODULE}), '
        f"and {why}this imports the `{project}` root: import the package you "
        f"need, e.g. `from {project}.<package>.<module> import <name>`, "
        f"not the `{project}` root.",
    )


def edge_violation(package: str, allowed: tuple[str, ...], target: str) -> Found:
    may = f"only {named(allowed)}" if allowed else "no project package"
    return (
        "layering",
        allowed,
        f"`{package}` may import {may} besides itself, not `{target}`. "
        f"Move the code into a package that may import `{target}`, or, "
        f"if the layers really should change, add `{target}` to "
        f'`ALLOWED_IMPORTS["{package}"]` in {DATA_MODULE}.',
    )


def layering_violations(
    node: ast.Import | ast.ImportFrom, package: str, project: str
) -> Iterator[Found]:
    allowed = ALLOWED_IMPORTS.get(package, ())
    for target in project_targets(node, project):
        if package == project:
            if target.package is not None:
                yield root_module_violation(project, target.package)
        elif target.package is None:
            yield root_import_violation(package, allowed, target, project)
        elif target.package != package and target.package not in allowed:
            yield edge_violation(package, allowed, target.package)


def placement_violations(
    node: ast.Import | ast.ImportFrom, package: str
) -> Iterator[Found]:
    for top in top_level_names(node):
        homes = THIRD_PARTY_HOMES.get(top)
        if homes is None or package in homes:
            continue
        yield (
            "third-party placement",
            homes,
            f"`{top}` may be imported only in {named(homes)}, not in `{package}`. "
            f"Move the import into {named(homes)}, or, if `{top}` really belongs "
            f'elsewhere, change `THIRD_PARTY_HOMES["{top}"]` in {DATA_MODULE}.',
        )


def node_violations(
    node: ast.Import | ast.ImportFrom, package: str, project: str
) -> Iterator[Found]:
    if isinstance(node, ast.ImportFrom) and node.level > 0:
        yield (
            "relative import",
            (),
            "imports must be absolute, in the form "
            f"`from {project}.<package>.<module> import <name>`.",
        )
        return
    yield from layering_violations(node, package, project)
    yield from placement_violations(node, package)


def unknown_package_violation(shown: str, package: str) -> ImportViolation:
    return ImportViolation(
        shown,
        1,
        f"package {package}",
        "unknown package",
        PACKAGES,
        f"`{package}` is not a known package; the packages are "
        f"{named(PACKAGES)}. Add `{package}` to `PACKAGES` and give it a row "
        f"in `ALLOWED_IMPORTS` in {DATA_MODULE}, or move the module into an "
        "existing package.",
    )


def module_violations(
    path: Path, package_root: Path, display_root: Path
) -> list[ImportViolation]:
    shown = path.relative_to(display_root).as_posix()
    parts = path.relative_to(package_root).parts
    project = package_root.name
    package = parts[0] if len(parts) > 1 else project
    if len(parts) > 1 and package not in PACKAGES:
        return [unknown_package_violation(shown, package)]
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            found.extend(
                ImportViolation(
                    shown, node.lineno, ast.unparse(node), rule, allowed, detail
                )
                for rule, allowed, detail in node_violations(node, package, project)
            )
    return found


def import_violations(package_root: Path, display_root: Path) -> list[ImportViolation]:
    modules = sorted(package_root.rglob("*.py")) if package_root.is_dir() else []
    if not modules:
        raise FileNotFoundError(
            f"{package_root} holds no Python modules; "
            "point the import check at the `pulse_frame` source folder."
        )
    found = [
        violation
        for path in modules
        for violation in module_violations(path, package_root, display_root)
    ]
    return sorted(found, key=lambda violation: (violation.path, violation.line))
