import re
import tomllib
from collections.abc import Iterator
from pathlib import Path

import pytest

from pulse_frame import store
from tests.database import REPO, SUPABASE_IGNORED_FOLDERS

SUPABASE = REPO / "supabase"
CONFIG = SUPABASE / "config.toml"
DASHES = re.compile(r"[\u2013\u2014]")
PROJECT_ID = "pulse-frame"
OWN_PORTS = range(55320, 55330)
DEFAULT_PORTS = range(54320, 54330)
SERVICE_PORTS = [
    ("api", "port"),
    ("db", "port"),
    ("db", "shadow_port"),
    ("db", "pooler", "port"),
    ("studio", "port"),
    ("inbucket", "port"),
    ("analytics", "port"),
    ("edge_runtime", "inspector_port"),
]
DATABASE_PORT = 55322
POSTGRES_MAJOR = 17
SERVICES_OFF = [
    ("api",),
    ("db", "pooler"),
    ("db", "seed"),
    ("realtime",),
    ("studio",),
    ("inbucket",),
    ("storage",),
    ("storage", "s3_protocol"),
    ("auth",),
    ("edge_runtime",),
    ("analytics",),
]
API_SCHEMA_LISTS = ["schemas", "extra_search_path"]
NETWORK_RESTRICTION_LISTS = ["allowed_cidrs", "allowed_cidrs_v6"]


def load_config() -> dict:
    return tomllib.loads(CONFIG.read_text(encoding="utf-8"))


def section(config: dict, path: tuple[str, ...]) -> dict:
    for key in path:
        config = config[key]
    return config


def ports(table: dict, where: str = "") -> Iterator[tuple[str, int]]:
    for key, value in table.items():
        if isinstance(value, dict):
            yield from ports(value, f"{where}{key}.")
        elif key == "port" or key.endswith("_port"):
            yield f"{where}{key}", value


def supabase_files() -> list[Path]:
    return sorted(
        path
        for path in SUPABASE.rglob("*")
        if path.is_file()
        and not SUPABASE_IGNORED_FOLDERS & set(path.relative_to(SUPABASE).parts)
    )


def test_config_names_the_pulse_frame_project() -> None:
    assert load_config()["project_id"] == PROJECT_ID


def test_database_listens_on_its_own_port() -> None:
    assert load_config()["db"]["port"] == DATABASE_PORT


def test_no_port_is_a_supabase_default() -> None:
    clashing = sorted(
        name for name, port in ports(load_config()) if port in DEFAULT_PORTS
    )
    assert clashing == [], f"ports on the Supabase defaults: {clashing}"


@pytest.mark.parametrize("path", SERVICE_PORTS, ids=".".join)
def test_service_port_sits_in_the_pulse_frame_range(path: tuple[str, ...]) -> None:
    *table, key = path
    assert section(load_config(), tuple(table))[key] in OWN_PORTS


def test_database_major_version_matches_the_local_image() -> None:
    assert load_config()["db"]["major_version"] == POSTGRES_MAJOR


@pytest.mark.parametrize("path", SERVICES_OFF, ids=".".join)
def test_every_service_but_the_database_is_off(path: tuple[str, ...]) -> None:
    assert section(load_config(), path)["enabled"] is False


def test_studio_has_no_openai_key() -> None:
    assert load_config()["studio"]["openai_api_key"] == ""


@pytest.mark.parametrize("key", API_SCHEMA_LISTS)
def test_data_api_never_lists_the_store_schema(key: str) -> None:
    listed = load_config()["api"][key]
    assert store.STORE_SCHEMA not in listed, f"`api.{key}` lists {listed}"


@pytest.mark.parametrize("key", NETWORK_RESTRICTION_LISTS)
def test_network_restrictions_allow_no_address(key: str) -> None:
    assert load_config()["db"]["network_restrictions"][key] == []


def test_no_em_or_en_dash_in_the_supabase_folder() -> None:
    files = supabase_files()
    assert CONFIG in files
    dashed = [
        f"{path.relative_to(REPO).as_posix()}:{number}"
        for path in files
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        )
        if DASHES.search(line)
    ]
    assert dashed == [], f"lines holding an em or en dash: {dashed}"
