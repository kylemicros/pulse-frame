from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.architecture.allowed_imports import PACKAGES
from tests.architecture.import_check import ImportViolation, import_violations

PROJECT = "pulse_frame"
NO_PROJECT_PACKAGE = "no project package"
ENTRY_ALLOWED = ("signal", "vision", "platform", "monitor")
DATA_MODULE = "backend/tests/architecture/allowed_imports.py"
ROOT_IMPORT = "not the `pulse_frame` root"
ABSOLUTE_FORM = "from pulse_frame.<package>.<module> import <name>"
INTERNAL_POINTERS = ("wiki", ".md", "ticket", "decision")

COMPLIANT_TREE = {
    "__init__.py": "",
    "signal/__init__.py": "",
    "signal/filters.py": "import numpy as np\n",
    "signal/pos.py": (
        "import cv2\n"
        "import numpy as np\n"
        "from pulse_frame.signal.filters import bandpass\n"
    ),
    "vision/__init__.py": "",
    "vision/motion.py": "import cv2\n",
    "vision/landmarks.py": (
        "import mediapipe as mp\n"
        "from mediapipe.tasks import python\n"
        "from pulse_frame.vision import motion\n"
    ),
    "platform/__init__.py": "",
    "platform/sandbox.py": "import ctypes\nimport pulse_frame.platform.errors\n",
    "platform/errors.py": "",
    "monitor/__init__.py": "",
    "monitor/processor.py": (
        "from typing import TYPE_CHECKING\n"
        "import pulse_frame.vision.landmarks\n"
        "from pulse_frame.signal.pos import pos\n"
        "if TYPE_CHECKING:\n"
        "    from pulse_frame.vision.motion import MotionGate\n"
        "def build():\n"
        "    from pulse_frame.signal import filters\n"
        "    return filters\n"
    ),
    "stream/__init__.py": "",
    "stream/app.py": (
        "from fastapi import FastAPI\n"
        "from fastapi.encoders import jsonable_encoder\n"
        "from starlette.websockets import WebSocket\n"
        "from pulse_frame import monitor\n"
        "from pulse_frame.platform.sandbox import apply_loopback_sandbox\n"
        "from pulse_frame.signal.pos import pos\n"
        "from pulse_frame.stream.errors import WIRE_ERRORS\n"
        "from pulse_frame.vision.landmarks import FaceTracker\n"
    ),
    "stream/errors.py": "",
    "stream/__main__.py": (
        "def main():\n"
        "    import uvicorn\n"
        "    from pulse_frame.stream.app import create_app\n"
        "    return uvicorn, create_app\n"
    ),
    "tools/__init__.py": "",
    "tools/live_check.py": (
        "from typing import TYPE_CHECKING\n"
        "import cv2\n"
        "from pulse_frame.platform.sandbox import apply_loopback_sandbox\n"
        "from pulse_frame.signal.pos import pos\n"
        "from pulse_frame.vision.landmarks import FaceTracker\n"
        "if TYPE_CHECKING:\n"
        "    from pulse_frame.monitor.processor import FrameProcessor\n"
        "def run():\n"
        "    from pulse_frame.monitor.processor import FrameProcessor\n"
        "    return FrameProcessor\n"
    ),
}


@dataclass(frozen=True)
class Planted:
    module: str
    source: str
    line: int
    statement: str
    rule: str
    allowed: tuple[str, ...]


TYPE_CHECKING_HEADER = "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n"
FUNCTION_HEADER = "import json\n\ndef load():\n"

LEAF_IMPORTS_A_PACKAGE = [
    Planted(
        "signal/planted.py",
        "import numpy as np\nfrom pulse_frame.vision.landmarks import FaceTracker\n",
        2,
        "from pulse_frame.vision.landmarks import FaceTracker",
        "layering",
        (),
    ),
    Planted(
        "vision/planted.py",
        "import pulse_frame.signal.pos\n",
        1,
        "import pulse_frame.signal.pos",
        "layering",
        (),
    ),
    Planted(
        "platform/planted.py",
        "from pulse_frame import monitor\n",
        1,
        "from pulse_frame import monitor",
        "layering",
        (),
    ),
]

MONITOR_IMPORTS_PLATFORM = [
    Planted(
        "monitor/planted.py",
        "from pulse_frame.platform.sandbox import apply_loopback_sandbox\n",
        1,
        "from pulse_frame.platform.sandbox import apply_loopback_sandbox",
        "layering",
        ("signal", "vision"),
    ),
]

PACKAGE_IMPORTS_AN_ENTRY = [
    Planted(
        "monitor/planted.py",
        "from pulse_frame.stream.app import create_app\n",
        1,
        "from pulse_frame.stream.app import create_app",
        "layering",
        ("signal", "vision"),
    ),
    Planted(
        "monitor/planted.py",
        "import pulse_frame.tools.live_check\n",
        1,
        "import pulse_frame.tools.live_check",
        "layering",
        ("signal", "vision"),
    ),
    Planted(
        "vision/planted.py",
        "from pulse_frame import stream\n",
        1,
        "from pulse_frame import stream",
        "layering",
        (),
    ),
]

ENTRIES_IMPORT_EACH_OTHER = [
    Planted(
        "stream/planted.py",
        "from pulse_frame.tools.live_check import run\n",
        1,
        "from pulse_frame.tools.live_check import run",
        "layering",
        ENTRY_ALLOWED,
    ),
    Planted(
        "tools/planted.py",
        "from pulse_frame.stream.app import create_app\n",
        1,
        "from pulse_frame.stream.app import create_app",
        "layering",
        ENTRY_ALLOWED,
    ),
]

RELATIVE_IMPORTS = [
    Planted(
        "signal/planted.py",
        "from . import filters\n",
        1,
        "from . import filters",
        "relative import",
        (),
    ),
    Planted(
        "monitor/planted.py",
        "import numpy as np\nfrom ..signal.pos import pos\n",
        2,
        "from ..signal.pos import pos",
        "relative import",
        (),
    ),
    Planted(
        "stream/planted.py",
        "from .errors import WIRE_ERRORS\n",
        1,
        "from .errors import WIRE_ERRORS",
        "relative import",
        (),
    ),
    Planted(
        "signal/planted.py",
        "from .mediapipe import x\n",
        1,
        "from .mediapipe import x",
        "relative import",
        (),
    ),
]

WEB_MODULE_OUTSIDE_STREAM = [
    Planted(
        "tools/planted.py",
        "import fastapi\n",
        1,
        "import fastapi",
        "third-party placement",
        ("stream",),
    ),
    Planted(
        "monitor/planted.py",
        "from fastapi.encoders import jsonable_encoder\n",
        1,
        "from fastapi.encoders import jsonable_encoder",
        "third-party placement",
        ("stream",),
    ),
    Planted(
        "vision/planted.py",
        "from starlette.websockets import WebSocket\n",
        1,
        "from starlette.websockets import WebSocket",
        "third-party placement",
        ("stream",),
    ),
    Planted(
        "tools/planted.py",
        "import uvicorn.config\n",
        1,
        "import uvicorn.config",
        "third-party placement",
        ("stream",),
    ),
]

MEDIAPIPE_OUTSIDE_VISION = [
    Planted(
        "signal/planted.py",
        "import mediapipe as mp\n",
        1,
        "import mediapipe as mp",
        "third-party placement",
        ("vision",),
    ),
    Planted(
        "monitor/planted.py",
        "from mediapipe.tasks import python\n",
        1,
        "from mediapipe.tasks import python",
        "third-party placement",
        ("vision",),
    ),
]

TYPE_CHECKING_IMPORTS = [
    Planted(
        "signal/planted.py",
        TYPE_CHECKING_HEADER
        + "    from pulse_frame.monitor.processor import FrameProcessor\n",
        3,
        "from pulse_frame.monitor.processor import FrameProcessor",
        "layering",
        (),
    ),
    Planted(
        "vision/planted.py",
        TYPE_CHECKING_HEADER + "    from fastapi import WebSocket\n",
        3,
        "from fastapi import WebSocket",
        "third-party placement",
        ("stream",),
    ),
]

FUNCTION_IMPORTS = [
    Planted(
        "monitor/planted.py",
        FUNCTION_HEADER + "    import pulse_frame.platform.sandbox\n    return 1\n",
        4,
        "import pulse_frame.platform.sandbox",
        "layering",
        ("signal", "vision"),
    ),
    Planted(
        "tools/planted.py",
        FUNCTION_HEADER
        + "    from pulse_frame.stream.app import create_app\n    return create_app\n",
        4,
        "from pulse_frame.stream.app import create_app",
        "layering",
        ENTRY_ALLOWED,
    ),
    Planted(
        "signal/planted.py",
        FUNCTION_HEADER + "    from . import pos\n    return pos\n",
        4,
        "from . import pos",
        "relative import",
        (),
    ),
]


ROOT_MODULE_IMPORTS = [
    Planted(
        "__init__.py",
        "import pulse_frame.signal\n",
        1,
        "import pulse_frame.signal",
        "layering",
        (),
    ),
    Planted(
        "__init__.py",
        "from fastapi import FastAPI\n",
        1,
        "from fastapi import FastAPI",
        "third-party placement",
        ("stream",),
    ),
]

PACKAGE_ROOT_IMPORTS = [
    Planted(
        "signal/planted.py",
        "import pulse_frame\n",
        1,
        "import pulse_frame",
        "layering",
        (),
    ),
    Planted(
        "vision/planted.py",
        "from pulse_frame import __version__\n",
        1,
        "from pulse_frame import __version__",
        "layering",
        (),
    ),
    Planted(
        "monitor/planted.py",
        "from pulse_frame import __version__\n",
        1,
        "from pulse_frame import __version__",
        "layering",
        ("signal", "vision"),
    ),
]

MULTI_NAME_IMPORTS = [
    Planted(
        "monitor/planted.py",
        "import numpy, fastapi\n",
        1,
        "import numpy, fastapi",
        "third-party placement",
        ("stream",),
    ),
    Planted(
        "signal/planted.py",
        "import pulse_frame.signal.pos, pulse_frame.stream.app\n",
        1,
        "import pulse_frame.signal.pos, pulse_frame.stream.app",
        "layering",
        (),
    ),
]


def case_id(planted: Planted) -> str:
    return f"{planted.module}:{planted.statement}"


def plant(root: Path, files: dict[str, str]) -> Path:
    package_root = root / "src" / PROJECT
    for relative, source in files.items():
        path = package_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return package_root


def planted_violations(root: Path, planted: Planted) -> list[ImportViolation]:
    package_root = plant(root, {**COMPLIANT_TREE, planted.module: planted.source})
    return import_violations(package_root, root)


def assert_names_only_in_repo_pointers(violation: ImportViolation) -> None:
    for pointer in INTERNAL_POINTERS:
        assert pointer not in violation.message.lower(), violation.message


def assert_single_violation(root: Path, planted: Planted) -> ImportViolation:
    violations = planted_violations(root, planted)
    assert len(violations) == 1, [violation.message for violation in violations]
    violation = violations[0]
    shown_path = f"src/{PROJECT}/{planted.module}"
    assert violation.path == shown_path
    assert violation.line == planted.line
    assert violation.statement == planted.statement
    assert violation.rule == planted.rule
    assert violation.allowed == planted.allowed
    assert f"{shown_path}:{planted.line}" in violation.message
    assert planted.statement in violation.message
    assert planted.rule in violation.message
    for home in planted.allowed:
        assert f"`{home}`" in violation.message
    if planted.rule == "layering" and not planted.allowed:
        assert NO_PROJECT_PACKAGE in violation.message
    if planted.rule == "layering" and planted.module != "__init__.py":
        importer = planted.module.split("/")[0]
        assert f'ALLOWED_IMPORTS["{importer}"]' in violation.message
        assert DATA_MODULE in violation.message
    if planted.rule == "third-party placement":
        assert 'THIRD_PARTY_HOMES["' in violation.message
        assert DATA_MODULE in violation.message
    assert_names_only_in_repo_pointers(violation)
    return violation


def test_compliant_planted_tree_passes(tmp_path: Path) -> None:
    package_root = plant(tmp_path, COMPLIANT_TREE)
    violations = import_violations(package_root, tmp_path)
    assert violations == [], [violation.message for violation in violations]


@pytest.mark.parametrize("planted", LEAF_IMPORTS_A_PACKAGE, ids=case_id)
def test_leaf_importing_a_project_package_fails(
    tmp_path: Path, planted: Planted
) -> None:
    assert_single_violation(tmp_path, planted)


@pytest.mark.parametrize("planted", MONITOR_IMPORTS_PLATFORM, ids=case_id)
def test_monitor_importing_platform_fails(tmp_path: Path, planted: Planted) -> None:
    assert_single_violation(tmp_path, planted)


@pytest.mark.parametrize("planted", PACKAGE_IMPORTS_AN_ENTRY, ids=case_id)
def test_package_importing_stream_or_tools_fails(
    tmp_path: Path, planted: Planted
) -> None:
    assert_single_violation(tmp_path, planted)


@pytest.mark.parametrize("planted", ENTRIES_IMPORT_EACH_OTHER, ids=case_id)
def test_stream_and_tools_importing_each_other_fails(
    tmp_path: Path, planted: Planted
) -> None:
    assert_single_violation(tmp_path, planted)


@pytest.mark.parametrize("planted", RELATIVE_IMPORTS, ids=case_id)
def test_relative_import_fails_and_names_the_absolute_form(
    tmp_path: Path, planted: Planted
) -> None:
    violation = assert_single_violation(tmp_path, planted)
    assert f"from {PROJECT}." in violation.message


@pytest.mark.parametrize("planted", WEB_MODULE_OUTSIDE_STREAM, ids=case_id)
def test_web_module_outside_stream_fails(tmp_path: Path, planted: Planted) -> None:
    assert_single_violation(tmp_path, planted)


@pytest.mark.parametrize("planted", MEDIAPIPE_OUTSIDE_VISION, ids=case_id)
def test_mediapipe_outside_vision_fails(tmp_path: Path, planted: Planted) -> None:
    assert_single_violation(tmp_path, planted)


@pytest.mark.parametrize("planted", TYPE_CHECKING_IMPORTS, ids=case_id)
def test_import_under_type_checking_counts(tmp_path: Path, planted: Planted) -> None:
    assert_single_violation(tmp_path, planted)


@pytest.mark.parametrize("planted", FUNCTION_IMPORTS, ids=case_id)
def test_import_inside_a_function_counts(tmp_path: Path, planted: Planted) -> None:
    assert_single_violation(tmp_path, planted)


def test_module_in_a_package_missing_from_the_table_fails(tmp_path: Path) -> None:
    package_root = plant(
        tmp_path, {**COMPLIANT_TREE, "extra/__init__.py": "", "extra/thing.py": ""}
    )
    violations = import_violations(package_root, tmp_path)
    assert sorted(violation.path for violation in violations) == [
        f"src/{PROJECT}/extra/__init__.py",
        f"src/{PROJECT}/extra/thing.py",
    ]
    for violation in violations:
        assert violation.rule == "unknown package"
        assert "`extra`" in violation.message
        for package in PACKAGES:
            assert f"`{package}`" in violation.message
        assert "`PACKAGES`" in violation.message
        assert "`ALLOWED_IMPORTS`" in violation.message
        assert DATA_MODULE in violation.message
        assert_names_only_in_repo_pointers(violation)


@pytest.mark.parametrize("planted", ROOT_MODULE_IMPORTS, ids=case_id)
def test_package_root_module_follows_the_tables(
    tmp_path: Path, planted: Planted
) -> None:
    violation = assert_single_violation(tmp_path, planted)
    if planted.rule == "layering":
        assert "root module" in violation.message
        assert "ALLOWED_IMPORTS[" not in violation.message


def test_package_root_module_may_import_the_root_itself(tmp_path: Path) -> None:
    root_source = "from pulse_frame import __version__\n"
    package_root = plant(tmp_path, {**COMPLIANT_TREE, "__init__.py": root_source})
    violations = import_violations(package_root, tmp_path)
    assert violations == [], [violation.message for violation in violations]


@pytest.mark.parametrize("planted", PACKAGE_ROOT_IMPORTS, ids=case_id)
def test_importing_the_package_root_fails_and_says_so(
    tmp_path: Path, planted: Planted
) -> None:
    violation = assert_single_violation(tmp_path, planted)
    assert ROOT_IMPORT in violation.message
    assert "import the package you need" in violation.message
    assert ABSOLUTE_FORM in violation.message
    if "__version__" in planted.statement:
        assert "`__version__` is not a package" in violation.message


@pytest.mark.parametrize("planted", MULTI_NAME_IMPORTS, ids=case_id)
def test_multi_name_import_fails_once_for_its_one_offending_name(
    tmp_path: Path, planted: Planted
) -> None:
    assert_single_violation(tmp_path, planted)


def test_multi_name_import_fails_once_per_offending_name(tmp_path: Path) -> None:
    statement = "import pulse_frame.vision.landmarks, pulse_frame.stream.app"
    package_root = plant(
        tmp_path, {**COMPLIANT_TREE, "signal/planted.py": f"{statement}\n"}
    )
    violations = import_violations(package_root, tmp_path)
    assert [(v.line, v.rule, v.statement) for v in violations] == [
        (1, "layering", statement),
        (1, "layering", statement),
    ]
    assert "not `vision`" in violations[0].message
    assert "not `stream`" in violations[1].message


def test_every_violation_in_one_module_is_reported(tmp_path: Path) -> None:
    source = (
        "import fastapi\n"
        "from . import filters\n"
        "from pulse_frame.monitor.processor import FrameProcessor\n"
    )
    package_root = plant(tmp_path, {**COMPLIANT_TREE, "signal/planted.py": source})
    violations = import_violations(package_root, tmp_path)
    assert [(violation.line, violation.rule) for violation in violations] == [
        (1, "third-party placement"),
        (2, "relative import"),
        (3, "layering"),
    ]


def test_violations_come_back_in_line_order(tmp_path: Path) -> None:
    source = (
        "import json\n"
        "\n"
        "def load():\n"
        "    import fastapi\n"
        "    return fastapi\n"
        "\n"
        "from pulse_frame.monitor.processor import FrameProcessor\n"
    )
    package_root = plant(tmp_path, {**COMPLIANT_TREE, "signal/planted.py": source})
    violations = import_violations(package_root, tmp_path)
    assert [(violation.line, violation.rule) for violation in violations] == [
        (4, "third-party placement"),
        (7, "layering"),
    ]


def test_missing_source_root_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="no Python modules"):
        import_violations(tmp_path / "src" / PROJECT, tmp_path)
