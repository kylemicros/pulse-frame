import contextlib
import gzip
import io
import itertools
import os
import shutil
import string
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import privacy_scan

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = "backend/tests/fixtures/astronaut.jpg"
ICONS = (
    "frontend/public/apple-touch-icon.png",
    "frontend/public/favicon.ico",
    "frontend/public/icon-192.png",
    "frontend/public/icon-512.png",
    "frontend/public/icon-maskable-512.png",
)


def joined(*parts):
    return "".join(parts)


BASE_AUTHOR = joined("base.author", "@", "example.org")
PAST_CONTRIBUTOR = joined("past.contributor", "@", "example.com")
UNKNOWN_EMAIL = joined("stranger", "@", "example.net")
WEB_MERGE = joined("noreply", "@github.com")
USERS_NOREPLY = joined("12345678+someone", "@users.noreply.github.com")
ALNUM = "x7Kq2Lm9Pz4Rt6Vw1Yb3Nc5Hd8Jf0Gs2Ak4UeQ1oP9iW3"
AWS_KEY = joined("AK", "IA", "QZ7K2LM9PZ4RT6VW")
PRIVATE_IP = joined("10.77", ".3.41")
CLAUDE_TMP = joined("clau", "de-123")
NO_AT_EMAIL = "zqnobody"

CONTENT_PLANTS = [
    ("path", joined("/Us", "ers/zed/notes.txt")),
    ("path", joined("/ho", "me/zed/notes.txt")),
    ("path", joined("/private", "/tmp/build/x.log")),
    ("path", joined("/private", "/var/db/x")),
    ("path", joined("/var", "/folders/ab/cd/T/x")),
    ("path", joined("/Vol", "umes/Backup/x")),
    ("path", joined("clau", "de-123")),
    ("path", joined("Personal", " Projects")),
    ("path", joined("C:", "\\Users\\zed")),
    ("private IP", PRIVATE_IP),
    ("private IP", joined("172.20", ".4.9")),
    ("private IP", joined("192.168", ".1.23")),
    ("link-local IP", joined("169.254", ".10.20")),
    ("MAC address", joined("0a:1b:2c", ":3d:4e:5f")),
    ("key", joined("gh", "p_", ALNUM[:36])),
    ("key", joined("gh", "o_", ALNUM[:36])),
    ("key", joined("gh", "u_", ALNUM[:36])),
    ("key", joined("gh", "s_", ALNUM[:36])),
    ("key", joined("gh", "r_", ALNUM[:36])),
    ("key", joined("github", "_pat_", (ALNUM * 2)[:22], "_", (ALNUM * 2)[:59])),
    ("key", AWS_KEY),
    ("key", joined("s", "k-", (ALNUM * 2)[:48])),
    ("key", joined("AI", "za", ALNUM[:35])),
    ("key", joined("xo", "xb-", "123456789012-1234567890123-", ALNUM[:24])),
    ("key", joined("-----BEGIN OPENSSH ", "PRIVATE", " KEY-----")),
    ("key", joined("GH_", "TOKEN=", "abc123")),
    ("key", joined("GH_", "TOKEN: ", "abc123")),
    ("email", UNKNOWN_EMAIL),
]
DATA_EXTENSIONS = ["npz", "npy", "csv", "mp4", "mov", "webm", "wav", "task", "tflite", "onnx"]
IMAGES = {
    "png": b"\x89PNG\r\n\x1a\n" + bytes(64),
    "jpg": b"\xff\xd8\xff\xe0" + bytes(64),
    "jpeg": b"\xff\xd8\xff\xe0" + bytes(64),
    "gif": b"GIF89a" + bytes(64),
    "webp": b"RIFF\x00\x00\x00\x00WEBPVP8 " + bytes(64),
    "heic": b"\x00\x00\x00\x18ftypheic" + bytes(64),
    "heif": b"\x00\x00\x00\x18ftypmif1" + bytes(64),
    "avif": b"\x00\x00\x00\x1cftypavif" + bytes(64),
    "bmp": b"BM" + bytes(64),
    "tif": b"II*\x00" + bytes(64),
    "tiff": b"MM\x00*" + bytes(64),
    "ico": b"\x00\x00\x01\x00" + bytes(64),
}
NAME_LEAKS = [
    ("path", f"notes/{CLAUDE_TMP}.txt", CLAUDE_TMP),
    ("private IP", f"notes/{PRIVATE_IP}.txt", PRIVATE_IP),
]
ALLOWED = [
    ("web merge noreply", WEB_MERGE),
    ("users noreply", USERS_NOREPLY),
    ("pytest decorators", '@pytest.mark.parametrize("x", [1])\\n@pytest.fixture'),
    ("loopback", "http://127.0.0.1:8000 http://localhost:5173"),
    ("ci runner home", "/home/runner/work/pulse-frame/pulse-frame"),
    ("system library", "/System/Library/Frameworks/Metal.framework/Metal"),
    ("usr lib", "/usr/lib/libSystem.B.dylib"),
    ("apple service", "com.apple.nsurlsessiond"),
    ("public range neighbours", "172.15.0.1 172.32.0.1 192.169.1.1"),
    ("ipv6 neighbours", joined("fe", "7f::1 fec0::1 fc00::1 2001:db8::9")),
]
NOTES = "notes/today.txt"
CASE_AND_ESCAPE_PLANTS = [
    ("path", joined("/us", "ers/zed/notes.txt")),
    ("path", joined("/US", "ERS/zed/notes.txt")),
    ("path", joined("\\/Us", "ers\\/zed\\/notes.txt")),
    ("path", joined("personal", " projects")),
    ("path", joined("PERSONAL", " PROJECTS")),
    ("path", joined("~/.claude/projects/-Us", "ers-zed-notes/session.jsonl")),
    ("private IP", joined("fd", "12:3456:789a::1")),
    ("link-local IP", joined("fe", "80::1c2d:3e4f:5a6b:7c8d")),
    ("link-local IP", joined("fe", "bf::1")),
]
BINARY_BLOBS = [
    (NOTES, "plain notes\n".encode("utf-16")),
    ("notes/today.txt.gz", gzip.compress(b"plain notes\n", mtime=0)),
    ("notes/blob.bin", b"plain\x00notes\n"),
]
MIGRATION = "supabase/migrations/20261116070812_session_store.sql"
SCHEMA_ONLY = (
    "create table public.sessions (\n"
    "    id bigint generated always as identity primary key,\n"
    "    started_at timestamptz not null default now(),\n"
    "    bpm real check (bpm > 0)\n"
    ");\n"
    "create index sessions_started_at on public.sessions (started_at);\n"
    "alter table public.sessions enable row level security;\n"
)
EXEMPT_MIGRATIONS = [
    MIGRATION,
    "supabase/migrations/20261117093000_add_quality.sql",
]
NOT_EXEMPT_SQL = [
    "supabase/seed.sql",
    "supabase/schemas/20261116070812_session_store.sql",
    "supabase/migrations/sub/20261116070812_session_store.sql",
    "supabase/migrations/20261116070812_session_store.SQL",
    "supabase/migrations/20261116070812_session_store.Sql",
    "supabase/migrations/20261116070812_Session_Store.sql",
    "supabase/migrations/2026111607081_session_store.sql",
    "supabase/migrations/202611160708120_session_store.sql",
    "supabase/migrations/20261116070812.sql",
    "supabase/migrations/session_store.sql",
    "supabase/Migrations/20261116070812_session_store.sql",
    "backend/supabase/migrations/20261116070812_session_store.sql",
    "backend/tests/store/schema.sql",
    "schema.sql",
]
NEVER_EXEMPT_DUMPS = [
    "supabase/migrations/20261116070812_session_store.dump",
    "supabase/migrations/20261116070812_session_store.backup",
    "supabase/migrations/20261116070812_session_store.DUMP",
    "data/session.dump",
    "data/session.backup",
    "data/session.Backup",
]
SQL_DATA_PLANTS = [
    ("copy upper", "COPY public.sessions (id, bpm) FROM stdin;\n1\t72\n\\.\n"),
    ("copy lower", "copy public.sessions from stdin;\n"),
    ("backslash copy", "\\copy public.sessions from 'rows.csv' csv\n"),
    ("insert upper", "INSERT INTO public.sessions (bpm) SELECT 72;\n"),
    ("insert lower", "insert into public.sessions (bpm) select 72;\n"),
    ("values row list", "select * from (VALUES (1, 72), (2, 75)) as t(id, bpm);\n"),
    ("values row list lower", "select * from (values\n  (1, 72)) as t(id, bpm);\n"),
    ("pg_dump header", "--\n-- PostgreSQL database dump\n--\n\n-- Dumped from database version 17.6\n"),
]
COMMENT_HIDDEN_PLANTS = [
    ("insert with an empty block comment", "insert/**/into public.sessions (bpm) select 72;\n"),
    ("insert with a multi line block comment", "INSERT/* a\n b */INTO public.sessions (bpm) select 72;\n"),
    ("insert with a line comment", "insert -- x\n into public.sessions (bpm) select 72;\n"),
    ("values with an empty block comment", "select * from (values/**/(1, 72)) as t(id, bpm);\n"),
    ("values with a line comment", "select * from (VALUES -- rows\n(1, 72)) as t(id, bpm);\n"),
]
SELECT_INTO_AND_CREATE_AS_PLANTS = [
    ("select into", "select * into public.sessions_copy from public.sessions;\n"),
    ("select into table upper", "SELECT id, bpm INTO TABLE public.sessions_copy FROM public.sessions;\n"),
    ("select into across lines", "select id,\n  bpm\ninto public.sessions_copy\nfrom public.sessions;\n"),
    ("select into behind a comment", "select */**/into public.sessions_copy from public.sessions;\n"),
    ("create table as", "create table public.sessions_copy as select * from public.sessions;\n"),
    (
        "create table if not exists as upper",
        "CREATE TABLE IF NOT EXISTS public.sessions_copy AS TABLE public.sessions;\n",
    ),
    (
        "create table as with columns",
        "create table public.sessions_copy (id, bpm) as select id, bpm from public.sessions;\n",
    ),
    ("create temp table as", "create temp table sessions_copy as select * from public.sessions;\n"),
    ("create table as across lines", "create table public.sessions_copy\nas\nselect * from public.sessions;\n"),
    ("create table as behind a comment", "create table public.sessions_copy/* x */as select * from public.sessions;\n"),
]
SCHEMA_COMMENTS = [
    ("line comment with copy to", "-- copy this to the next migration when the table changes\n"),
    ("line comment with insert into", "-- the capture tool will insert into public.sessions later\n"),
    ("line comment with values row", "-- values (1, 72) are examples only\n"),
    ("block comment with copy from", "/*\n copy rows from the capture tool, never from here\n*/\n"),
    ("block comment with select into", "/* select bpm into a report elsewhere */\n"),
    ("block comment with create table as", "/* create table public.x as select 1 is not allowed here */\n"),
]
TRIGGER_AFTER_INSERT = (
    "create function public.touch_session() returns trigger language plpgsql as $$\n"
    "begin\n"
    "  new.started_at = now();\n"
    "  return new;\n"
    "end\n"
    "$$;\n"
    "create trigger sessions_touch after insert on public.sessions\n"
    "  for each row execute function public.touch_session();\n"
)
BEATS_TABLE = (
    "create table public.beats (\n"
    "    id bigint generated always as identity primary key,\n"
    "    session_id bigint not null references public.sessions (id) on delete cascade\n"
    ");\n"
)
SCHEMA_CLAUSES = [
    (
        "rls policy for insert",
        "create policy sessions_insert on public.sessions for insert to authenticated with check (true);\n",
    ),
    ("trigger after insert", TRIGGER_AFTER_INSERT),
    ("view as select", "create view public.session_summary as select id, bpm from public.sessions;\n"),
    ("second table with an identity column", BEATS_TABLE),
]
STRING_HIDDEN_PLANTS = [
    (
        "line comment marker inside a string",
        "comment on table public.sessions is 'a--b'; insert into public.sessions (bpm) select 72;\n",
    ),
    (
        "block comment markers inside strings across lines",
        (
            "comment on table public.sessions is 'x/*';\n"
            "insert into public.sessions (bpm) select 72;\n"
            "comment on column public.sessions.bpm is '*/';\n"
        ),
    ),
    (
        "line comment marker inside a quoted identifier",
        'create table public."a--b" (id bigint primary key); insert into public.sessions (bpm) select 72;\n',
    ),
    (
        "line comment marker inside an escape string",
        "comment on table public.sessions is E'\\'--'; insert into public.sessions (bpm) select 72;\n",
    ),
    (
        "line comment inside a dollar quoted body",
        (
            "create function public.note() returns integer language sql as $$ select 1 -- it's $$; "
            "insert into public.sessions (bpm) select 72;\n"
        ),
    ),
    (
        "line comment inside a tagged dollar quoted body",
        (
            "create function public.note() returns integer language sql as $fn$ select 1 -- it's $fn$; "
            "insert into public.sessions (bpm) select 72;\n"
        ),
    ),
]
DO_BLOCK_PLANTS = [
    ("execute inside a do block", "do $$ begin execute 'insert into public.sessions (bpm) select 72'; end $$;\n"),
    (
        "execute inside a tagged do block",
        "do $body$\nbegin\n  execute 'insert into public.sessions (bpm) select 72';\nend\n$body$;\n",
    ),
]
TRIGGER_WITH_QUOTES = (
    "create function public.stamp_session() returns trigger language plpgsql as $$\n"
    "begin\n"
    "  -- it's the server clock\n"
    "  new.started_at = now();\n"
    "  return new;\n"
    "end\n"
    "$$;\n"
    "-- the capture tool, not this file, will insert into public.sessions\n"
)
QUOTED_SCHEMA = [
    (
        "comments holding quotes around a data word",
        "-- the owner's capture tool will insert into public.sessions later\n/* it's never done here */\n",
    ),
    ("block comment holding a dollar quote", "/* don't write $$ insert into public.sessions $$ here */\n"),
    (
        "rls policy with a string",
        (
            "create policy sessions_owner on public.sessions for select to authenticated "
            "using (current_setting('app.owner', true) = 'yes');\n"
        ),
    ),
    ("trigger function with a dollar body", TRIGGER_WITH_QUOTES),
    ("identity column", BEATS_TABLE),
]
CREATE_AS_EVASIONS = [
    ("create table with storage options as", "create table private.t with (fillfactor = 70) as select 1 as a;\n"),
    ("create table using an access method as", "create table private.t using heap as select 1;\n"),
    ("create table with a quoted name as", 'create table "odd name" as select 1;\n'),
    ("create table with columns and options as", "create table t (a) with (fillfactor = 70) as select 1;\n"),
    ("create materialized view as", "create materialized view v as select 1 as a, 2 as b;\n"),
]
NOT_CREATE_AS = [
    ("view as select", "create view public.session_summary as select id, bpm from public.sessions;\n"),
    ("identity column", BEATS_TABLE),
    (
        "generated column",
        "create table public.readings (\n    bpm real,\n    doubled real generated always as (bpm * 2) stored\n);\n",
    ),
    (
        "function returning a table with a dollar body",
        (
            "create function public.recent() returns table (id bigint) language sql "
            "as $$ select id from public.sessions $$;\n"
        ),
    ),
]
BIG_SCHEMA = "".join(f"create table public.t_{index} (id bigint primary key);\n" for index in range(2500))
SLOW_TO_LEX = "".join("$" + "".join(tag) + "$\n" for tag in itertools.product(string.ascii_lowercase, repeat=3))
NOT_A_MIGRATION = "db/schema.sql"
SCAN_BOUND_SECONDS = 2.0
MISSING_HEAD = "0123456789abcdef0123456789abcdef01234567"
DEPENDABOT_ADDRESS = joined("support", "@", "github.com")
DEPENDABOT_SIGNOFF = f"Signed-off-by: dependabot[bot] <{DEPENDABOT_ADDRESS}>"
DEPENDABOT_MESSAGE = "\n".join(
    [
        "build(deps): bump vite from 7.1.0 to 7.1.1 in /frontend",
        "",
        "Bumps [vite](https://github.com/vitejs/vite) from 7.1.0 to 7.1.1.",
        "",
        "---",
        "updated-dependencies:",
        "- dependency-name: vite",
        "  dependency-version: 7.1.1",
        "",
        DEPENDABOT_SIGNOFF,
        "",
    ]
)
SIGNOFF_ELSEWHERE = [
    ("address in the subject", f"docs: ask {DEPENDABOT_ADDRESS}"),
    ("address in the body", f"docs: notes\n\nask {DEPENDABOT_ADDRESS} about it\n\n{DEPENDABOT_SIGNOFF}"),
    ("sign-off line in the body", f"docs: notes\n\n{DEPENDABOT_SIGNOFF}\n\nmore notes"),
    ("another trailer", f"docs: notes\n\nCo-authored-by: dependabot[bot] <{DEPENDABOT_ADDRESS}>"),
    ("another name", f"docs: notes\n\nSigned-off-by: someone <{DEPENDABOT_ADDRESS}>"),
    ("lower case token", f"docs: notes\n\nsigned-off-by: dependabot[bot] <{DEPENDABOT_ADDRESS}>"),
    ("indented line", f"docs: notes\n\n  {DEPENDABOT_SIGNOFF}"),
    ("text after the line", f"docs: notes\n\n{DEPENDABOT_SIGNOFF} thanks"),
    ("a second address in the trailers", f"docs: notes\n\n{DEPENDABOT_SIGNOFF}\nCc: {UNKNOWN_EMAIL}"),
]


ALLOWED_HOSTS_FILE = REPO_ROOT / ".github" / "allowed-hosts.txt"
UNTRUSTED_HOST = "untrusted host"
GITHUB = "github.com"
PYPI = "pypi.org"
MIRROR_LIKE = joined("github-com.", "lookalike.", "cloudns.ch")
RAW_MIRROR_LIKE = joined("raw-githubusercontent-com.", "lookalike.", "cloudns.ch")
SUBSTITUTES = "qxz7"


def url(host, rest="/owner/repo"):
    return joined("https", "://", host, rest)


def remote(host):
    return joined("git", "@", host, ":owner/repo.git")


HTTPS_LOOKALIKES = [
    ("github lookalike under cloudns", url(MIRROR_LIKE)),
    ("raw content lookalike under cloudns", url(RAW_MIRROR_LIKE, "/owner/repo/master/README.md")),
    ("listed host as the prefix of another domain", url(joined(GITHUB, ".lookalike.invalid"))),
    ("one character off", url(joined("githu", "h.com"))),
    ("upper case", url(GITHUB.upper())),
    ("mixed case", url(joined("Git", "Hub.com"))),
    ("trailing dot", url(joined(GITHUB, "."))),
    ("listed host as a path", url("lookalike.invalid", joined("/", GITHUB, "/owner/repo"))),
    ("no path", url(MIRROR_LIKE, "")),
    ("with a port", url(MIRROR_LIKE, ":443/owner/repo")),
    ("http scheme", joined("http", "://", MIRROR_LIKE, "/owner/repo")),
    ("in a markdown link", joined("[repo](", url(MIRROR_LIKE), ")")),
    ("in quotes", joined('"', url(MIRROR_LIKE), '"')),
    ("in angle brackets", joined("<", url(MIRROR_LIKE), ">")),
]
AT_SIGN_LOOKALIKES = [
    ("listed host as user info", url(joined(GITHUB, "@", "lookalike.invalid"))),
    ("cloudns remote", remote(MIRROR_LIKE)),
    ("one character off remote", remote(joined("githu", "h.com"))),
    ("upper case remote", remote(GITHUB.upper())),
    ("trailing dot remote", remote(joined(GITHUB, "."))),
    ("listed host as the prefix of another domain remote", remote(joined(GITHUB, ".lookalike.invalid"))),
    ("ssh scheme with user", joined("ssh", "://", "git", "@", MIRROR_LIKE, "/owner/repo.git")),
]
EVIL = joined("evil", ".invalid")
LIST_PATH = ".github/allowed-hosts.txt"
START_ONLY = joined("mirror", ".start-only", ".invalid")
EXEMPT_HOSTS = frozenset({"localhost", "host", "postgres"})
SPECIAL_SCHEMES = ["http", "https", "ws", "wss", "ftp"]
STRICT_HOST_PLANTS = [
    ("backslash-before-at", joined("https", "://", EVIL, "\\", "@", GITHUB, "/x")),
    ("backslash-before-example", joined("https", "://", EVIL, "\\", ".example", "/x")),
    ("percent-encoded-dot", joined("https", "://", "evil", "%2E", "invalid", "/x")),
    ("ideographic-full-stop", joined("https", "://", "evil", "\u3002", "invalid", "/x")),
    ("fullwidth-full-stop", joined("https", "://", "evil", "\uff0e", "invalid", "/x")),
    ("decimal-ipv4", joined("http", "://", "16843009", "/x")),
    ("hex-ipv4", joined("http", "://", "0x", "01010101", "/x")),
    ("bracketed-ipv6", joined("https", "://", "[2001", ":db8::1]", "/x")),
    ("tab-inside-the-host", joined("https", "://", "evil", "\t", ".invalid", "/x")),
    ("shell-variable", joined("https", "://", "${", "MIRROR}", "/x")),
    ("listed-host-then-quote", joined("https", "://", GITHUB, "'", ".", EVIL, "/x")),
    ("listed-host-then-parenthesis", joined("https", "://", GITHUB, "(", ".", EVIL, "/x")),
]
DOTLESS_PLANTS = [
    ("single-label", joined("https", "://", "intra", "net", "/x")),
    ("near-an-exempt-name", joined("https", "://", "postgres", "ql", "/x")),
    ("single-label-with-a-port", joined("http", "://", "intra", "net", ":8080/x")),
    ("single-label-remote", remote(joined("intra", "net"))),
]
EMPTY_HOST_PLANTS = [(f"{scheme}-three-slashes", joined(scheme, ":", "///", EVIL, "/x")) for scheme in SPECIAL_SCHEMES] + [
    ("https-four-slashes", joined("https", ":", "////", EVIL, "/x")),
]
SPECIAL_SCHEME_PLANTS = [
    plant
    for scheme in SPECIAL_SCHEMES
    for plant in (
        (f"{scheme}-no-slashes", joined(scheme, ":", EVIL, "/x")),
        (f"{scheme}-two-backslashes", joined(scheme, ":", "\\\\", EVIL, "/x")),
        (f"{scheme}-slash-then-backslash", joined(scheme, ":", "/", "\\", EVIL, "/x")),
    )
] + [("upper-case-https-no-slashes", joined("HTTPS", ":", EVIL, "/x"))]
LOOPBACK = joined("127.0", ".0.1")
ANGLE_PLANTS = [
    ("listed-host-then-angle-at", joined("https", "://", GITHUB, "<", "@", EVIL, "/x")),
    ("listed-host-then-angle-user-at", joined("https", "://", GITHUB, "<", "x", "@", EVIL, "/x")),
    ("listed-host-port-then-angle-at", joined("https", "://", GITHUB, ":443", "<", "@", EVIL, "/x")),
    ("loopback-then-angle-at", joined("http", "://", LOOPBACK, "<", "@", EVIL, "/x")),
    ("listed-host-then-angle-dot", joined("https", "://", GITHUB, "<", ".", EVIL, "/x")),
]
WHITESPACE_PLANTS = [
    ("listed-host-tab-dot", joined(url(GITHUB, ""), "\t", ".", EVIL, "/x")),
    ("listed-host-tab-at", joined(url(GITHUB, ""), "\t", "@", EVIL, "/x")),
    ("tab-inside-the-slashes", joined("https", ":", "\t", "//", EVIL, "/x")),
    ("tab-before-the-colon", joined("https", "\t", "://", EVIL, "/x")),
    ("listed-host-carriage-return-dot", joined(url(GITHUB, ""), "\r", ".", EVIL, "/x")),
    ("listed-host-space-at", joined(url(GITHUB, ""), " ", "@", EVIL, "/x")),
    ("listed-host-space-user-at", joined(url(GITHUB, ""), " ", "x", "@", EVIL, "/x")),
]
SPACE_RUN_PLANTS = [
    ("listed-url-space-quote-at", joined(url(GITHUB, ""), " ", '"', "@", EVIL, "/x")),
    ("single-quoted-href-space-quote-at", joined("href='", url(GITHUB, ""), " ", '"', "@", EVIL, "/x'")),
    ("markdown-angle-space-quote-at", joined("[x](<", url(GITHUB, ""), " ", '"', "@", EVIL, "/x>)")),
    ("double-quoted-href-space-angle-at", joined('href="', url(GITHUB, ""), " ", ">", "@", EVIL, '/x"')),
    ("markdown-angle-space-backslash-angle-at", joined("[x](<", url(GITHUB, ""), " ", "\\", ">", "@", EVIL, "/x>)")),
    ("markdown-angle-space-backslash-at", joined("[x](<", url(GITHUB, ""), " ", "\\", "@", EVIL, "/x>)")),
    ("listed-url-quote-at", joined(url(GITHUB, ""), '"', "@", EVIL, "/x")),
    ("listed-url-angle-at", joined(url(GITHUB, ""), ">", "@", EVIL, "/x")),
    ("listed-url-backslash-at", joined(url(GITHUB, ""), "\\", "@", EVIL, "/x")),
]
MULTI_WORD_RUN_PLANTS = [
    ("listed-url-space-words-at", joined(url(GITHUB, ""), " x y", "@", EVIL, "/x")),
]
LONG_PLAIN_LINE = "a" * 100_000
LONG_TRAILER_LINE = joined("https", "://", ")" * 100_000, "x")
SECOND_COLON_PLANTS = [
    ("allowed-origins-list", joined("ALLOWED_ORIGINS=", "http", "://", "localhost", ":5173", ",", "https", "://", EVIL)),
    ("json-origin-array", joined('["', "http", "://", "localhost", ":5173", '","', "https", "://", EVIL, '/x"]')),
    ("listed-port-comma-url", joined("https", "://", GITHUB, ":443", ",", "https", "://", EVIL, "/x")),
    ("listed-port-semicolon-url", joined("https", "://", GITHUB, ":443", ";", "https", "://", EVIL, "/x")),
    ("space-between-urls", joined("http", "://", "localhost", ":5173", " ", "https", "://", EVIL)),
]
PORT_PLACEHOLDER_PASSES = [
    ("loopback-port-placeholder", joined('f"', "ws", "://", LOOPBACK, ":{port}{path}", '"')),
    ("user-at-loopback-port-placeholder", joined("postgresql", "://", "user", "@", LOOPBACK, ":port")),
    ("user-at-host-port-placeholder", joined("postgresql", "://", "user", "@", "host", ":port")),
]
SPECIAL_SCHEME_EXEMPT_PLANTS = [
    (f"{name}-on-{scheme}", joined(scheme, "://", name, "/x")) for name in ("host", "postgres") for scheme in SPECIAL_SCHEMES
]
TRAILER_PLANTS = [
    ("evil-host-then-quote-comma", joined('"', url(EVIL, ""), '",')),
]
DEPARTURE_PASSES = [
    ("placeholder-authority", joined("pg-functions", "://", "<database>", "/x")),
    ("listed-host-then-closing-tag", joined(url(GITHUB, ""), "</a>")),
    ("listed-path-then-tag", joined(url(GITHUB, "/x"), "<br>")),
    ("listed-url-then-prose", joined(url(GITHUB, "/x"), " and more prose")),
    ("listed-host-then-prose", joined(url(GITHUB, ""), " is where the code lives")),
    ("listed-host-in-quotes-then-comma", joined('"', url(GITHUB, ""), '",')),
    ("listed-host-in-parentheses-then-semicolon", joined("(", url(GITHUB, ""), ");")),
    ("yaml-ws-key", joined("    ", "ws", ":", " true")),
    ("scheme-alone-in-parentheses", joined("(", "https", ":", ")")),
    ("postgres-user-at-localhost", joined("postgresql", "://", "postgres", "@", "localhost")),
    ("postgres-on-pg-functions", joined("pg-functions", "://", "postgres", "/x")),
] + [(f"localhost-on-{scheme}", joined(scheme, "://", "localhost", ":5173/x")) for scheme in SPECIAL_SCHEMES]
RESERVED_SUFFIX_PLANTS = [
    ("listed-host-then-example-then-more", url(joined(GITHUB, ".example", ".invalid"))),
    ("example-dot-com", url(joined("example", ".", "com"))),
]
PASSING_HOSTS = [
    ("localhost", joined("http", "://", "localhost", ":5173/x")),
    ("host", joined("postgresql", "://", "user", ":", "pw", "@", "host", ":5432/db")),
    ("postgres", joined("pg-functions", "://", "postgres")),
    ("file-with-an-empty-host", joined("file", ":", "///", "tmp/x")),
    ("markdown-link", joined("[repo](", url(GITHUB, "/x"), ")")),
    ("markdown-link-without-a-path", joined("[repo](", url(GITHUB, ""), ")")),
    ("double-quotes", joined('"', url(GITHUB, ""), '"')),
    ("single-quotes", joined("'", url(GITHUB, ""), "'")),
    ("backticks", joined("`", url(GITHUB, ""), "`")),
    ("angle-brackets", joined("<", url(GITHUB, ""), ">")),
    ("listed-host-then-example", url(joined(GITHUB, ".example"))),
    ("name-under-example", url(joined("x", ".example"))),
]


def listed_hosts(case):
    case.assertTrue(ALLOWED_HOSTS_FILE.is_file(), f"{ALLOWED_HOSTS_FILE.name} is missing from .github")
    return ALLOWED_HOSTS_FILE.read_bytes().decode("ascii").splitlines()


def one_character_off(host, listed):
    for index, character in enumerate(host):
        if character.isalnum():
            for substitute in SUBSTITUTES:
                candidate = joined(host[:index], substitute, host[index + 1 :])
                if substitute != character and candidate not in listed:
                    return candidate
    raise AssertionError(f"no one character variant of {host} is off the list")


def lookalikes_of(host, listed):
    variants = [
        one_character_off(host, listed),
        joined(host, ".lookalike.invalid"),
        joined("zz-unlisted.", host),
        joined(host, "."),
    ]
    if host.upper() != host:
        variants.append(host.upper())
    return [variant for variant in variants if variant not in listed]


def temp_folder(case):
    folder = Path(tempfile.mkdtemp(prefix="privacyscan-"))
    case.addCleanup(shutil.rmtree, folder, True)
    return folder


class Repo:
    def __init__(self, case):
        self.root = temp_folder(case)
        home = self.root / "home"
        home.mkdir()
        self.env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(home),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
        self.path = self.root / "repo"
        self.git("init", "-q", "-b", "master", str(self.path), cwd=self.root)
        self.git("config", "user.name", "Base Author")
        self.git("config", "user.email", BASE_AUTHOR)
        self.git("config", "commit.gpgsign", "false")
        self.base = self.commit({"README.md": "hello\n"}, "start")

    def git(self, *args, cwd=None, extra_env=None):
        env = dict(self.env, **(extra_env or {}))
        done = subprocess.run(["git", *args], cwd=cwd or self.path, env=env, capture_output=True, check=True)
        return done.stdout.decode().strip()

    def commit(self, files, message, author=None, committer=None, deleted=()):
        for rel, data in files.items():
            path = self.path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data if isinstance(data, bytes) else data.encode())
        if files:
            self.git("add", "-f", "--", *files)
        if deleted:
            self.git("rm", "-q", "--", *deleted)
        extra = {}
        if author:
            extra["GIT_AUTHOR_EMAIL"] = author
        if committer:
            extra["GIT_COMMITTER_EMAIL"] = committer
        self.git("commit", "-q", "--allow-empty", "-m", message, extra_env=extra)
        return self.git("rev-parse", "HEAD")

    def scan(self, base=None):
        return privacy_scan.scan_range(str(self.path), base or self.base, self.git("rev-parse", "HEAD"))

    def cli(self, base, head):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = privacy_scan.main(["--repo", str(self.path), "--base", base, "--head", head])
        return code, out.getvalue() + err.getvalue()

    def evil_merge(self, files):
        self.git("checkout", "-q", "-b", "side")
        self.commit({"notes/side.txt": "side notes\n"}, "docs: side notes")
        self.git("checkout", "-q", "master")
        self.commit({"notes/main.txt": "main notes\n"}, "docs: main notes")
        self.git("merge", "-q", "--no-ff", "--no-commit", "side")
        for rel, data in files.items():
            path = self.path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(data)
        self.git("add", "-f", "--", *files)
        self.git("commit", "-q", "-m", "Merge branch side")
        return self.git("rev-parse", "HEAD")


def found(findings):
    return {(finding.kind, finding.path) for finding in findings}


class PlantedLeakTests(unittest.TestCase):
    def test_each_content_pattern_in_an_added_line_is_found_by_kind_and_file(self):
        for kind, text in CONTENT_PLANTS:
            with self.subTest(text=text):
                repo = Repo(self)
                repo.commit({NOTES: f"seen {text} here\n"}, "docs: add notes")
                self.assertEqual(found(repo.scan()), {(kind, NOTES)})

    def test_each_content_pattern_in_a_commit_message_is_found_with_the_commit(self):
        for kind, text in CONTENT_PLANTS:
            with self.subTest(text=text):
                repo = Repo(self)
                sha = repo.commit({NOTES: "plain notes\n"}, f"docs: notes {text}")
                findings = repo.scan()
                self.assertEqual({finding.kind for finding in findings}, {kind})
                self.assertTrue(all(sha[:7] in finding.path for finding in findings), found(findings))

    def test_env_files_are_found_and_the_example_passes(self):
        for name in (".env", ".env.local", "backend/.env.production"):
            with self.subTest(name=name):
                repo = Repo(self)
                repo.commit({name: "MODE=dev\n"}, "chore: settings")
                self.assertEqual(found(repo.scan()), {("env file", name)})
        repo = Repo(self)
        repo.commit({".env.example": "MODE=dev\n"}, "chore: settings example")
        self.assertEqual(repo.scan(), [])

    def test_each_data_and_model_extension_is_found(self):
        for extension in DATA_EXTENSIONS:
            with self.subTest(extension=extension):
                repo = Repo(self)
                name = f"data/session.{extension}"
                repo.commit({name: b"\x00\x01\x02payload\n"}, "data: add a session")
                self.assertEqual(found(repo.scan()), {("data file", name), ("binary file", name)})

    def test_unpinned_images_are_found(self):
        for extension, data in IMAGES.items():
            with self.subTest(extension=extension):
                repo = Repo(self)
                name = f"docs/shot.{extension}"
                repo.commit({name: data}, "docs: add a shot")
                self.assertEqual(found(repo.scan()), {("image", name), ("binary file", name)})

    def test_pinned_fixture_passes_and_a_changed_or_moved_copy_is_found(self):
        pinned = (REPO_ROOT / FIXTURE).read_bytes()
        repo = Repo(self)
        with_fixture = repo.commit({FIXTURE: pinned}, "test: add the fixture")
        self.assertEqual(repo.scan(), [])
        repo.commit({FIXTURE: pinned + b"\x00"}, "test: touch the fixture")
        self.assertEqual(found(repo.scan(base=with_fixture)), {("image", FIXTURE), ("binary file", FIXTURE)})
        moved = Repo(self)
        moved.commit({"docs/astronaut.jpg": pinned}, "docs: reuse the fixture")
        self.assertEqual(found(moved.scan()), {("image", "docs/astronaut.jpg"), ("binary file", "docs/astronaut.jpg")})

    def test_pinned_icons_pass_and_changed_bytes_or_an_unpinned_neighbour_are_found(self):
        for icon in ICONS:
            with self.subTest(icon=icon):
                pinned = (REPO_ROOT / icon).read_bytes()
                repo = Repo(self)
                with_icon = repo.commit({icon: pinned}, "feat: add the icon")
                self.assertEqual(repo.scan(), [])
                repo.commit({icon: pinned + b"\x00"}, "feat: touch the icon")
                self.assertEqual(found(repo.scan(base=with_icon)), {("image", icon), ("binary file", icon)})
        neighbour = "frontend/public/icon-256.png"
        repo = Repo(self)
        repo.commit({neighbour: IMAGES["png"]}, "feat: add another icon")
        self.assertEqual(found(repo.scan()), {("image", neighbour), ("binary file", neighbour)})

    def test_new_file_over_the_size_limit_is_found_but_an_edit_to_an_old_one_is_not(self):
        repo = Repo(self)
        repo.commit({"docs/big.txt": "lorem ipsum\n" * 26000}, "docs: add a big file")
        self.assertEqual(found(repo.scan()), {("large file", "docs/big.txt")})
        before_edit = repo.git("rev-parse", "HEAD")
        repo.commit({"docs/big.txt": "lorem ipsum\n" * 26000 + "one more line\n"}, "docs: extend the big file")
        self.assertEqual(repo.scan(base=before_edit), [])

    def test_new_lockfiles_over_the_size_limit_pass(self):
        repo = Repo(self)
        big = "lorem ipsum\n" * 26000
        repo.commit({"backend/uv.lock": big, "frontend/pnpm-lock.yaml": big}, "chore: lock dependencies")
        self.assertEqual(repo.scan(), [])

    def test_deleting_a_data_file_passes(self):
        repo = Repo(self)
        with_data = repo.commit({"data/old.csv": "t,r\n0,1\n"}, "data: old session")
        repo.commit({}, "data: drop the old session", deleted=("data/old.csv",))
        self.assertEqual(repo.scan(base=with_data), [])

    def test_leak_added_then_removed_inside_the_range_is_still_found(self):
        repo = Repo(self)
        repo.commit({NOTES: f"seen {PRIVATE_IP} here\n"}, "docs: add notes")
        repo.commit({NOTES: "plain notes\n"}, "docs: tidy notes")
        self.assertEqual(found(repo.scan()), {("private IP", NOTES)})

    def test_unknown_author_or_committer_email_is_found_with_the_commit(self):
        for role in ("author", "committer"):
            with self.subTest(role=role):
                repo = Repo(self)
                sha = repo.commit({NOTES: "plain notes\n"}, "docs: add notes", **{role: UNKNOWN_EMAIL})
                findings = repo.scan()
                self.assertEqual({finding.kind for finding in findings}, {"email"})
                self.assertTrue(all(sha[:7] in finding.path for finding in findings), found(findings))

    def test_author_email_without_an_at_sign_is_found_with_the_commit(self):
        repo = Repo(self)
        sha = repo.commit({NOTES: "plain notes\n"}, "docs: add notes", author=NO_AT_EMAIL)
        self.assertEqual(found(repo.scan()), {("email", f"commit {sha[:7]} author")})

    def test_merge_commit_adding_a_leaking_file_is_found(self):
        repo = Repo(self)
        repo.evil_merge({"notes/evil.txt": f"seen {PRIVATE_IP} here\n"})
        self.assertEqual(found(repo.scan()), {("private IP", "notes/evil.txt")})


class BinaryDodgeTests(unittest.TestCase):
    def test_leak_in_a_file_marked_minus_diff_by_gitattributes_is_found(self):
        for attributes in ("*.txt -diff\n", "*.txt binary\n"):
            with self.subTest(attributes=attributes):
                repo = Repo(self)
                base = repo.commit({".gitattributes": attributes}, "chore: attributes")
                repo.commit({NOTES: f"seen {PRIVATE_IP} here\n"}, "docs: add notes")
                self.assertEqual(found(repo.scan(base=base)), {("private IP", NOTES)})

    def test_leak_in_a_file_with_a_nul_byte_is_found(self):
        repo = Repo(self)
        repo.commit({NOTES: f"seen {PRIVATE_IP} here\n".encode() + b"\x00\n"}, "docs: add notes")
        self.assertEqual(found(repo.scan()), {("private IP", NOTES), ("binary file", NOTES)})

    def test_a_gitattributes_change_is_found(self):
        for name in (".gitattributes", "docs/.gitattributes"):
            with self.subTest(name=name):
                repo = Repo(self)
                repo.commit({name: "*.sh text eol=lf\n"}, "chore: attributes")
                self.assertIn(name, {finding.path for finding in repo.scan()})


class BinaryFileTests(unittest.TestCase):
    def test_added_blob_with_a_nul_byte_is_a_binary_file(self):
        for name, data in BINARY_BLOBS:
            with self.subTest(name=name):
                repo = Repo(self)
                repo.commit({name: data}, "docs: add notes")
                self.assertEqual(found(repo.scan()), {("binary file", name)})

    def test_text_file_modified_into_a_blob_with_a_nul_byte_is_a_binary_file(self):
        repo = Repo(self)
        base = repo.commit({NOTES: "plain notes\n"}, "docs: add notes")
        repo.commit({NOTES: "plain notes\n".encode("utf-16")}, "docs: re-encode notes")
        self.assertEqual(found(repo.scan(base=base)), {("binary file", NOTES)})

    def test_binary_file_finding_prints_kind_and_file_and_fails(self):
        repo = Repo(self)
        head = repo.commit({"notes/today.txt.gz": gzip.compress(b"plain notes\n", mtime=0)}, "docs: add notes")
        code, output = repo.cli(repo.base, head)
        self.assertEqual(code, 1)
        self.assertIn("binary file: notes/today.txt.gz", output)


class CaseAndEscapeTests(unittest.TestCase):
    def test_case_escaped_slug_and_ipv6_patterns_in_an_added_line_are_found(self):
        for kind, text in CASE_AND_ESCAPE_PLANTS:
            with self.subTest(text=text):
                repo = Repo(self)
                repo.commit({NOTES: f"seen {text} here\n"}, "docs: add notes")
                self.assertEqual(found(repo.scan()), {(kind, NOTES)})

    def test_case_escaped_slug_and_ipv6_patterns_in_a_commit_message_are_found(self):
        for kind, text in CASE_AND_ESCAPE_PLANTS:
            with self.subTest(text=text):
                repo = Repo(self)
                sha = repo.commit({NOTES: "plain notes\n"}, f"docs: notes {text}")
                self.assertEqual(found(repo.scan()), {(kind, f"commit {sha[:7]} message")})


class FileNameTests(unittest.TestCase):
    def test_file_name_matching_a_pattern_is_reported_as_a_file_name_without_the_name(self):
        for kind, name, literal in NAME_LEAKS:
            with self.subTest(kind=kind):
                repo = Repo(self)
                head = repo.commit({name: "plain notes\n"}, "docs: add notes")
                findings = repo.scan()
                self.assertIn(kind, {finding.kind for finding in findings})
                self.assertTrue(all(literal not in finding.path for finding in findings), found(findings))
                code, output = repo.cli(repo.base, head)
                self.assertEqual(code, 1)
                self.assertIn(kind, output)
                self.assertIn("a file name", output)
                self.assertNotIn(literal, output)

    def test_content_finding_in_a_leaking_file_name_never_prints_the_name(self):
        repo = Repo(self)
        head = repo.commit({f"notes/{CLAUDE_TMP}.txt": f"aws = {AWS_KEY}\n"}, "docs: add notes")
        code, output = repo.cli(repo.base, head)
        self.assertEqual(code, 1)
        self.assertIn("key", output)
        self.assertIn("a file name", output)
        self.assertNotIn(CLAUDE_TMP, output)
        self.assertNotIn(AWS_KEY, output)


class AllowlistTests(unittest.TestCase):
    def test_allowlisted_text_passes_in_added_lines_and_messages(self):
        for label, text in ALLOWED:
            with self.subTest(label=label):
                repo = Repo(self)
                repo.commit({NOTES: f"{text}\n"}, f"docs: {text}")
                self.assertEqual(repo.scan(), [])

    def test_email_already_in_the_base_history_passes_as_author_and_committer(self):
        repo = Repo(self)
        base = repo.commit({"docs/credits.txt": "thanks\n"}, "docs: credits", author=PAST_CONTRIBUTOR)
        repo.commit({NOTES: "plain notes\n"}, "docs: add notes", author=PAST_CONTRIBUTOR, committer=PAST_CONTRIBUTOR)
        self.assertEqual(repo.scan(base=base), [])

    def test_email_already_in_the_base_history_is_found_in_content_and_messages(self):
        for email in (PAST_CONTRIBUTOR, BASE_AUTHOR):
            with self.subTest(email=email):
                repo = Repo(self)
                base = repo.commit({"docs/credits.txt": "thanks\n"}, "docs: credits", author=PAST_CONTRIBUTOR)
                sha = repo.commit({NOTES: f"ask {email}\n"}, f"docs: ask {email}", author=PAST_CONTRIBUTOR)
                expected = {("email", NOTES), ("email", f"commit {sha[:7]} message")}
                self.assertEqual(found(repo.scan(base=base)), expected)

    def test_email_first_seen_inside_the_range_is_not_allowed_by_history(self):
        repo = Repo(self)
        repo.commit({"docs/credits.txt": "thanks\n"}, "docs: credits", author=UNKNOWN_EMAIL)
        repo.commit({NOTES: f"ask {UNKNOWN_EMAIL}\n"}, "docs: add notes")
        self.assertIn(("email", NOTES), found(repo.scan()))

    def test_web_merge_committer_and_users_noreply_author_pass(self):
        repo = Repo(self)
        repo.commit(
            {NOTES: "plain notes\n"},
            "Merge pull request #8 from someone/feat",
            author=USERS_NOREPLY,
            committer=WEB_MERGE,
        )
        self.assertEqual(repo.scan(), [])


class UntrustedHostTests(unittest.TestCase):
    def test_named_lookalike_urls_in_an_added_line_are_untrusted_hosts(self):
        for label, text in HTTPS_LOOKALIKES:
            with self.subTest(label=label):
                repo = Repo(self)
                repo.commit({NOTES: f"see {text} now\n"}, "docs: add notes")
                self.assertEqual(found(repo.scan()), {(UNTRUSTED_HOST, NOTES)})

    def test_lookalike_git_remotes_and_user_info_urls_in_an_added_line_are_untrusted_hosts(self):
        for label, text in AT_SIGN_LOOKALIKES:
            with self.subTest(label=label):
                repo = Repo(self)
                repo.commit({NOTES: f"remote {text}\n"}, "docs: add notes")
                self.assertIn((UNTRUSTED_HOST, NOTES), found(repo.scan()))

    def test_lookalikes_of_every_listed_host_are_untrusted_hosts(self):
        listed = set(listed_hosts(self))
        files = {}
        for host in sorted(listed):
            for variant in lookalikes_of(host, listed):
                files[f"hosts/{len(files)}.txt"] = f"see {url(variant)} now\n"
        self.assertGreaterEqual(len(files), 4 * len(listed))
        repo = Repo(self)
        repo.commit(files, "docs: add hosts")
        self.assertEqual(found(repo.scan()), {(UNTRUSTED_HOST, name) for name in files})

    def test_every_listed_host_passes_with_ports_paths_queries_and_fragments(self):
        listed = listed_hosts(self)
        self.assertIn(GITHUB, listed)
        self.assertIn(PYPI, listed)
        files = {
            f"hosts/{index}.txt": f"see {url(host)} and {url(host, ':443/a/b?c=1#d')} now\n"
            for index, host in enumerate(listed)
        }
        repo = Repo(self)
        repo.commit(files, "docs: add hosts")
        self.assertEqual(repo.scan(), [])

    def test_github_and_pypi_urls_pass_and_the_github_remote_is_not_an_untrusted_host(self):
        repo = Repo(self)
        repo.commit({NOTES: f"see {url(GITHUB)} and {url(PYPI, '/simple/numpy/')}\n"}, "docs: add notes")
        self.assertEqual(repo.scan(), [])
        repo = Repo(self)
        repo.commit({NOTES: f"remote {remote(GITHUB)}\n"}, "docs: add notes")
        self.assertNotIn(UNTRUSTED_HOST, {finding.kind for finding in repo.scan()})

    def test_lookalike_removed_inside_the_range_passes(self):
        repo = Repo(self)
        base = repo.commit({NOTES: f"see {url(MIRROR_LIKE)} now\n"}, "docs: add notes")
        repo.commit({NOTES: f"see {url(GITHUB)} now\n"}, "docs: fix the host")
        self.assertEqual(repo.scan(base=base), [])

    def test_untrusted_host_prints_kind_and_file_without_the_host_and_fails(self):
        for text in (url(MIRROR_LIKE), remote(MIRROR_LIKE)):
            with self.subTest(text=text):
                repo = Repo(self)
                head = repo.commit({NOTES: f"see {text} now\n"}, "docs: add notes")
                code, output = repo.cli(repo.base, head)
                self.assertEqual(code, 1)
                self.assertIn(f"{UNTRUSTED_HOST}: {NOTES}", output)
                self.assertNotIn(MIRROR_LIKE, output)

    def test_lookalike_url_in_a_commit_message_is_found_with_the_commit_and_never_printed(self):
        repo = Repo(self)
        head = repo.commit({NOTES: "plain notes\n"}, f"docs: notes from {url(MIRROR_LIKE)}")
        self.assertEqual(found(repo.scan()), {(UNTRUSTED_HOST, f"commit {head[:7]} message")})
        code, output = repo.cli(repo.base, head)
        self.assertEqual(code, 1)
        self.assertIn(f"{UNTRUSTED_HOST}: commit {head[:7]} message", output)
        self.assertNotIn(MIRROR_LIKE, output)

    def test_listed_host_url_in_a_commit_message_passes(self):
        repo = Repo(self)
        head = repo.commit({NOTES: "plain notes\n"}, f"docs: notes from {url(GITHUB)} and {url(PYPI, '/simple/')}")
        self.assertEqual(repo.scan(), [])
        self.assertEqual(repo.cli(repo.base, head)[0], 0)

    def test_allowed_hosts_file_loads_as_its_lines(self):
        listed = listed_hosts(self)
        self.assertEqual(Path(privacy_scan.ALLOWED_HOSTS_FILE).resolve(), ALLOWED_HOSTS_FILE)
        self.assertEqual(set(privacy_scan.load_allowed_hosts(privacy_scan.ALLOWED_HOSTS_FILE)), set(listed))

    def test_missing_allowed_hosts_file_is_a_scan_error(self):
        missing = temp_folder(self) / "allowed-hosts.txt"
        with self.assertRaises(privacy_scan.ScanError):
            privacy_scan.load_allowed_hosts(missing)


def plant_files(plants):
    return {f"hosts/{label}.txt": f"see {text} now\n" for label, text in plants}


class StrictHostTests(unittest.TestCase):
    def assert_each_plant_is_an_untrusted_host(self, plants):
        files = plant_files(plants)
        repo = Repo(self)
        repo.commit(files, "docs: add hosts")
        self.assertEqual(found(repo.scan()), {(UNTRUSTED_HOST, name) for name in files})

    def assert_each_plant_has_an_untrusted_host(self, plants):
        files = plant_files(plants)
        repo = Repo(self)
        repo.commit(files, "docs: add hosts")
        untrusted = {path for kind, path in found(repo.scan()) if kind == UNTRUSTED_HOST}
        self.assertEqual(untrusted, set(files))

    def test_angle_bracket_after_the_host_does_not_end_the_authority(self):
        self.assert_each_plant_has_an_untrusted_host(ANGLE_PLANTS)

    def test_tab_and_carriage_return_are_removed_and_a_space_before_an_at_sign_is_untrusted(self):
        self.assert_each_plant_has_an_untrusted_host(WHITESPACE_PLANTS)

    def test_space_then_at_sign_run_is_not_stopped_by_quotes_angles_or_backslashes(self):
        self.assert_each_plant_is_an_untrusted_host(SPACE_RUN_PLANTS)
        self.assert_each_plant_has_an_untrusted_host(MULTI_WORD_RUN_PLANTS)

    def timed_host_findings(self, line):
        start = time.perf_counter()
        findings = privacy_scan.host_findings(line, NOTES, frozenset({GITHUB}))
        return findings, time.perf_counter() - start

    def test_one_hundred_kilobyte_plain_line_is_scanned_for_hosts_quickly(self):
        findings, elapsed = self.timed_host_findings(LONG_PLAIN_LINE)
        self.assertEqual(findings, [])
        self.assertLess(elapsed, SCAN_BOUND_SECONDS)

    def test_url_with_one_hundred_thousand_closing_parentheses_is_scanned_quickly(self):
        findings, elapsed = self.timed_host_findings(LONG_TRAILER_LINE)
        self.assertEqual(found(findings), {(UNTRUSTED_HOST, NOTES)})
        self.assertLess(elapsed, SCAN_BOUND_SECONDS)

    def test_second_colon_in_the_host_and_port_is_an_untrusted_host(self):
        self.assert_each_plant_is_an_untrusted_host(SECOND_COLON_PLANTS)

    def test_port_placeholders_after_a_trusted_host_pass(self):
        repo = Repo(self)
        repo.commit(plant_files(PORT_PLACEHOLDER_PASSES), "docs: add hosts")
        self.assertEqual(found(repo.scan()), set())

    def test_host_and_postgres_on_a_special_scheme_are_untrusted_hosts(self):
        self.assert_each_plant_is_an_untrusted_host(SPECIAL_SCHEME_EXEMPT_PLANTS)

    def test_untrusted_host_before_trimmed_quote_and_comma_is_an_untrusted_host(self):
        self.assert_each_plant_is_an_untrusted_host(TRAILER_PLANTS)

    def test_placeholders_tags_prose_trailers_yaml_keys_and_exempt_names_pass(self):
        repo = Repo(self)
        repo.commit(plant_files(DEPARTURE_PASSES), "docs: add hosts")
        self.assertEqual(found(repo.scan()), set())

    def test_hosts_outside_lower_case_letters_digits_dots_and_hyphens_are_untrusted_hosts(self):
        self.assert_each_plant_is_an_untrusted_host(STRICT_HOST_PLANTS)

    def test_dotless_hosts_outside_the_exempt_set_are_untrusted_hosts(self):
        self.assert_each_plant_is_an_untrusted_host(DOTLESS_PLANTS)

    def test_empty_host_on_a_special_scheme_is_an_untrusted_host(self):
        self.assert_each_plant_is_an_untrusted_host(EMPTY_HOST_PLANTS)

    def test_special_scheme_without_two_slashes_or_with_a_backslash_is_an_untrusted_host(self):
        self.assert_each_plant_is_an_untrusted_host(SPECIAL_SCHEME_PLANTS)

    def test_reserved_suffix_inside_the_host_or_example_dot_com_is_an_untrusted_host(self):
        self.assert_each_plant_is_an_untrusted_host(RESERVED_SUFFIX_PLANTS)

    def test_exempt_set_is_exactly_localhost_host_and_postgres(self):
        self.assertEqual(privacy_scan.EXEMPT_HOSTS, EXEMPT_HOSTS)
        self.assertEqual({host for host in EXEMPT_HOSTS if not privacy_scan.host_exempt(host)}, set())

    def test_exempt_names_reserved_suffix_file_urls_and_wrapped_listed_hosts_pass(self):
        repo = Repo(self)
        repo.commit(plant_files(PASSING_HOSTS), "docs: add hosts")
        self.assertEqual(found(repo.scan()), set())

    def test_listed_host_after_user_info_is_not_an_untrusted_host(self):
        repo = Repo(self)
        repo.commit({NOTES: f"see {url(joined('user', '@', GITHUB))} now\n"}, "docs: add notes")
        self.assertNotIn(UNTRUSTED_HOST, {finding.kind for finding in repo.scan()})


class StartCommitHostListTests(unittest.TestCase):
    def repo_with_list(self, hosts):
        repo = Repo(self)
        base = repo.commit({LIST_PATH: "".join(f"{host}\n" for host in hosts)}, "chore: list hosts")
        return repo, base

    def missing_tree_list(self):
        missing = temp_folder(self) / "allowed-hosts.txt"
        self.enterContext(mock.patch.object(privacy_scan, "ALLOWED_HOSTS_FILE", missing))

    def test_host_added_to_the_list_and_used_in_the_same_range_is_an_untrusted_host(self):
        repo, base = self.repo_with_list([GITHUB])
        repo.commit({LIST_PATH: f"{GITHUB}\n{PYPI}\n", NOTES: f"see {url(PYPI)} now\n"}, "docs: add notes")
        self.assertEqual(found(repo.scan(base=base)), {(UNTRUSTED_HOST, NOTES)})

    def test_host_listed_only_at_the_start_commit_passes(self):
        repo, base = self.repo_with_list([GITHUB, START_ONLY])
        repo.commit({NOTES: f"see {url(START_ONLY)} and {url(GITHUB)} now\n"}, "docs: add notes")
        self.assertEqual(repo.scan(base=base), [])

    def test_start_commit_without_a_list_uses_the_tree_list(self):
        repo = Repo(self)
        repo.commit({LIST_PATH: f"{START_ONLY}\n", NOTES: f"see {url(START_ONLY)} now\n"}, "chore: list hosts")
        self.assertEqual(found(repo.scan()), {(UNTRUSTED_HOST, NOTES)})
        repo = Repo(self)
        repo.commit({LIST_PATH: f"{START_ONLY}\n", NOTES: f"see {url(GITHUB)} now\n"}, "chore: list hosts")
        self.assertEqual(repo.scan(), [])

    def test_allowed_hosts_at_reads_the_start_commit_list_or_falls_back_to_the_tree(self):
        repo, base = self.repo_with_list([GITHUB, START_ONLY])
        git = privacy_scan.Git(str(repo.path))
        self.assertEqual(privacy_scan.allowed_hosts_at(git, base), frozenset({GITHUB, START_ONLY}))
        tree = privacy_scan.load_allowed_hosts(privacy_scan.ALLOWED_HOSTS_FILE)
        self.assertEqual(privacy_scan.allowed_hosts_at(git, repo.base), tree)

    def test_list_at_the_start_commit_scans_without_a_tree_list(self):
        self.missing_tree_list()
        repo, base = self.repo_with_list([GITHUB])
        head = repo.commit({NOTES: f"see {url(GITHUB)} now\n"}, "docs: add notes")
        self.assertEqual(repo.cli(base, head)[0], 0)

    def test_no_list_at_the_start_commit_or_in_the_tree_fails_closed_with_could_not_run(self):
        self.missing_tree_list()
        repo = Repo(self)
        head = repo.commit({NOTES: f"see {url(GITHUB)} now\n"}, "docs: add notes")
        code, output = repo.cli(repo.base, head)
        self.assertEqual(code, 2)
        self.assertIn("could not run", output)

    def test_non_ascii_line_in_the_start_commit_list_is_a_scan_error(self):
        repo, base = self.repo_with_list([GITHUB, joined("caf", "\u00e9", ".invalid")])
        head = repo.commit({NOTES: f"see {url(GITHUB)} now\n"}, "docs: add notes")
        with self.assertRaises(privacy_scan.ScanError):
            repo.scan(base=base)
        code, output = repo.cli(base, head)
        self.assertEqual(code, 2)
        self.assertIn("could not run", output)

    def test_git_failure_reading_the_start_commit_list_fails_closed_with_could_not_run(self):
        repo, base = self.repo_with_list([GITHUB])
        head = repo.commit({NOTES: f"see {url(GITHUB)} now\n"}, "docs: add notes")
        folder = repo.git("rev-parse", f"{base}:.github")
        loose = repo.path / ".git" / "objects" / folder[:2] / folder[2:]
        self.assertTrue(loose.is_file())
        loose.unlink()
        code, output = repo.cli(base, head)
        self.assertEqual(code, 2)
        self.assertIn("could not run", output)

    def test_list_lines_outside_the_host_form_trust_nothing(self):
        repo, base = self.repo_with_list([GITHUB, "", joined("Git", "Hub.com")])
        files = {
            "hosts/empty-host.txt": f"see {joined('https', ':', '///', EVIL, '/x')} now\n",
            "hosts/upper-case-host.txt": f"see {url(joined('Git', 'Hub.com'))} now\n",
        }
        repo.commit(files, "docs: add hosts")
        self.assertEqual(found(repo.scan(base=base)), {(UNTRUSTED_HOST, name) for name in files})

    def test_non_ascii_line_in_the_tree_list_is_a_scan_error(self):
        listed = temp_folder(self) / "allowed-hosts.txt"
        listed.write_bytes(joined(GITHUB, "\n", "caf", "\u00e9", ".invalid", "\n").encode())
        with self.assertRaises(privacy_scan.ScanError):
            privacy_scan.load_allowed_hosts(listed)


class DependabotSignoffTests(unittest.TestCase):
    def test_dependabot_sign_off_trailer_passes_in_a_commit_message(self):
        repo = Repo(self)
        repo.commit({NOTES: "plain notes\n"}, DEPENDABOT_MESSAGE)
        self.assertEqual(repo.scan(), [])

    def test_dependabot_address_anywhere_else_in_a_commit_message_is_found(self):
        for label, message in SIGNOFF_ELSEWHERE:
            with self.subTest(label=label):
                repo = Repo(self)
                sha = repo.commit({NOTES: "plain notes\n"}, message)
                self.assertEqual(found(repo.scan()), {("email", f"commit {sha[:7]} message")})

    def test_dependabot_sign_off_line_in_an_added_line_is_found(self):
        repo = Repo(self)
        repo.commit({NOTES: f"notes\n\n{DEPENDABOT_SIGNOFF}\n"}, "docs: add notes")
        self.assertEqual(found(repo.scan()), {("email", NOTES)})


class SqlMigrationTests(unittest.TestCase):
    def assert_each_plant_is_a_data_file(self, plants):
        for label, plant in plants:
            with self.subTest(label=label):
                repo = Repo(self)
                repo.commit({MIGRATION: SCHEMA_ONLY + plant}, "feat: add the session schema")
                self.assertEqual(found(repo.scan()), {("data file", MIGRATION)})

    def assert_each_plant_renamed_in_is_a_data_file(self, plants):
        for label, plant in plants:
            with self.subTest(label=label):
                repo = Repo(self)
                base = repo.commit({"notes/rows.txt": SCHEMA_ONLY + plant}, "docs: rows")
                (repo.path / MIGRATION).parent.mkdir(parents=True)
                repo.git("mv", "notes/rows.txt", MIGRATION)
                repo.commit({}, "feat: move the rows")
                self.assertEqual(found(repo.scan(base=base)), {("data file", MIGRATION)})

    def assert_each_clause_stays_schema_only(self, clauses):
        for label, clause in clauses:
            with self.subTest(label=label):
                repo = Repo(self)
                repo.commit({MIGRATION: SCHEMA_ONLY + clause}, "feat: add the session schema")
                self.assertEqual(found(repo.scan()), set())

    def assert_edit_is_a_data_file(self, content):
        repo = Repo(self)
        base = repo.commit({MIGRATION: SCHEMA_ONLY}, "feat: add the session schema")
        repo.commit({MIGRATION: content}, "feat: grow the session schema")
        self.assertEqual(found(repo.scan(base=base)), {("data file", MIGRATION)})

    def test_sql_dump_and_backup_files_are_data_files_anywhere_by_default(self):
        for name in ("data/session.sql", "data/session.dump", "data/session.backup", "notes/rows.SQL"):
            with self.subTest(name=name):
                repo = Repo(self)
                repo.commit({name: "-- rows\n"}, "data: add a session")
                self.assertEqual(found(repo.scan()), {("data file", name)})

    def test_schema_only_migration_passes_and_the_same_file_anywhere_else_is_a_data_file(self):
        cases = [(name, set()) for name in EXEMPT_MIGRATIONS]
        cases += [(name, {("data file", name)}) for name in NOT_EXEMPT_SQL]
        for name, expected in cases:
            with self.subTest(name=name):
                repo = Repo(self)
                repo.commit({name: SCHEMA_ONLY}, "feat: add the session schema")
                self.assertEqual(found(repo.scan()), expected)

    def test_dump_and_backup_are_never_exempt_even_in_the_migrations_folder(self):
        for name in NEVER_EXEMPT_DUMPS:
            with self.subTest(name=name):
                repo = Repo(self)
                repo.commit({name: SCHEMA_ONLY}, "feat: add the session schema")
                self.assertEqual(found(repo.scan()), {("data file", name)})

    def test_migration_carrying_rows_or_a_dump_header_is_a_data_file(self):
        self.assert_each_plant_is_a_data_file(SQL_DATA_PLANTS)

    def test_data_markers_split_by_a_comment_are_a_data_file(self):
        self.assert_each_plant_is_a_data_file(COMMENT_HIDDEN_PLANTS)

    def test_select_into_and_create_table_as_are_a_data_file(self):
        self.assert_each_plant_is_a_data_file(SELECT_INTO_AND_CREATE_AS_PLANTS)

    def test_select_into_and_create_table_as_renamed_into_the_migrations_folder_are_a_data_file(self):
        self.assert_each_plant_renamed_in_is_a_data_file(SELECT_INTO_AND_CREATE_AS_PLANTS)

    def test_comment_markers_inside_strings_identifiers_or_dollar_bodies_do_not_hide_data(self):
        self.assert_each_plant_is_a_data_file(STRING_HIDDEN_PLANTS)

    def test_data_inside_a_dollar_quoted_do_block_is_a_data_file(self):
        self.assert_each_plant_is_a_data_file(DO_BLOCK_PLANTS)

    def test_create_as_with_options_quoted_names_or_a_materialized_view_is_a_data_file(self):
        self.assert_each_plant_is_a_data_file(CREATE_AS_EVASIONS)

    def test_comments_naming_data_words_leave_a_schema_only_migration_exempt(self):
        for label, comment in SCHEMA_COMMENTS:
            for name, expected in ((MIGRATION, set()), (NOT_A_MIGRATION, {("data file", NOT_A_MIGRATION)})):
                with self.subTest(label=label, name=name):
                    repo = Repo(self)
                    repo.commit({name: SCHEMA_ONLY + comment}, "feat: add the session schema")
                    self.assertEqual(found(repo.scan()), expected)

    def test_insert_policies_triggers_views_and_identity_columns_stay_schema_only(self):
        self.assert_each_clause_stays_schema_only(SCHEMA_CLAUSES)

    def test_quotes_in_comments_policies_dollar_bodies_and_identity_columns_stay_schema_only(self):
        self.assert_each_clause_stays_schema_only(QUOTED_SCHEMA)

    def test_views_identity_and_generated_columns_and_table_functions_are_not_create_as(self):
        self.assert_each_clause_stays_schema_only(NOT_CREATE_AS)

    def test_rows_added_to_an_existing_migration_are_a_data_file(self):
        self.assert_edit_is_a_data_file(SCHEMA_ONLY + "INSERT INTO public.sessions (bpm) SELECT 72;\n")

    def test_data_bearing_file_renamed_into_the_migrations_folder_is_a_data_file(self):
        self.assert_each_plant_renamed_in_is_a_data_file(SQL_DATA_PLANTS)

    def test_exemption_removes_only_the_data_file_kind_and_content_checks_stay_on(self):
        plants = [
            ("path", joined("/Us", "ers/zed/notes.txt")),
            ("private IP", PRIVATE_IP),
            ("email", UNKNOWN_EMAIL),
            ("key", AWS_KEY),
        ]
        for kind, text in plants:
            for name, extra in ((MIGRATION, set()), (NOT_A_MIGRATION, {"data file"})):
                with self.subTest(kind=kind, name=name):
                    repo = Repo(self)
                    repo.commit({name: f"{SCHEMA_ONLY}-- seen {text} here\n"}, "feat: add the session schema")
                    expected = {(kind, name)} | {(other, name) for other in extra}
                    self.assertEqual(found(repo.scan()), expected)

    def test_exempt_migration_with_a_nul_byte_is_still_a_binary_file(self):
        for name, expected in ((MIGRATION, {"binary file"}), (NOT_A_MIGRATION, {"binary file", "data file"})):
            with self.subTest(name=name):
                repo = Repo(self)
                repo.commit({name: SCHEMA_ONLY.encode() + b"\x00\n"}, "feat: add the session schema")
                self.assertEqual(found(repo.scan()), {(kind, name) for kind in expected})

    def test_new_migration_over_the_size_limit_is_never_exempt_and_matches_any_other_sql_file(self):
        self.assertGreater(len(BIG_SCHEMA), privacy_scan.SIZE_LIMIT_BYTES)
        kinds = {}
        for name in (MIGRATION, NOT_A_MIGRATION):
            with self.subTest(name=name):
                repo = Repo(self)
                repo.commit({name: BIG_SCHEMA}, "feat: add the session schema")
                findings = found(repo.scan())
                kinds[name] = {kind for kind, _ in findings}
                self.assertEqual({path for _, path in findings}, {name})
                self.assertIn("data file", kinds[name])
                self.assertLessEqual(kinds[name], {"data file", "large file"})
        self.assertEqual(kinds.get(MIGRATION), kinds.get(NOT_A_MIGRATION))

    def test_modified_migration_over_the_size_limit_is_a_data_file(self):
        self.assertGreater(len(BIG_SCHEMA), privacy_scan.SIZE_LIMIT_BYTES)
        self.assert_edit_is_a_data_file(BIG_SCHEMA)

    def assert_slow_to_lex_edit_is_a_quick_data_file(self, name):
        self.assertGreater(len(SLOW_TO_LEX), privacy_scan.SIZE_LIMIT_BYTES)
        self.assertLess(len(SLOW_TO_LEX), privacy_scan.SIZE_LIMIT_BYTES * 1.1)
        repo = Repo(self)
        base = repo.commit({name: SCHEMA_ONLY}, "feat: add the session schema")
        repo.commit({name: SLOW_TO_LEX}, "feat: grow the session schema")
        start = time.monotonic()
        findings = repo.scan(base=base)
        elapsed = time.monotonic() - start
        self.assertEqual(found(findings), {("data file", name)})
        self.assertLess(elapsed, SCAN_BOUND_SECONDS)

    def test_migration_over_the_size_limit_that_is_slow_to_lex_is_a_data_file_quickly(self):
        self.assert_slow_to_lex_edit_is_a_quick_data_file(MIGRATION)

    def test_sql_file_outside_the_migrations_folder_that_is_slow_to_lex_is_a_data_file_quickly(self):
        self.assert_slow_to_lex_edit_is_a_quick_data_file(NOT_A_MIGRATION)


class CommandLineTests(unittest.TestCase):
    def test_findings_print_kind_and_file_without_the_matched_text_and_fail(self):
        repo = Repo(self)
        head = repo.commit({"config/settings.txt": f"aws = {AWS_KEY}\n"}, "chore: settings")
        code, output = repo.cli(repo.base, head)
        self.assertEqual(code, 1)
        self.assertIn("key", output)
        self.assertIn("config/settings.txt", output)
        self.assertNotIn(AWS_KEY, output)

    def test_message_findings_never_print_the_matched_text(self):
        repo = Repo(self)
        head = repo.commit({NOTES: "plain notes\n"}, f"docs: notes {PRIVATE_IP}")
        code, output = repo.cli(repo.base, head)
        self.assertEqual(code, 1)
        self.assertIn("private IP", output)
        self.assertIn(head[:7], output)
        self.assertNotIn(PRIVATE_IP, output)

    def test_head_that_does_not_exist_fails_closed_with_could_not_run(self):
        repo = Repo(self)
        code, output = repo.cli(repo.base, MISSING_HEAD)
        self.assertEqual(code, 2)
        self.assertIn("could not run", output)

    def test_clean_range_passes(self):
        repo = Repo(self)
        head = repo.commit({"backend/pulse.py": "def pulse():\n    return 72\n"}, "feat: add pulse")
        self.assertEqual(repo.cli(repo.base, head)[0], 0)

    def test_all_zero_base_scans_from_the_merge_base_with_master(self):
        for planted, expected in ((f"aws = {AWS_KEY}\n", 1), ("plain notes\n", 0)):
            with self.subTest(expected=expected):
                repo = Repo(self)
                repo.commit({"docs/old.txt": f"old {PRIVATE_IP}\n"}, "docs: old notes")
                repo.git("checkout", "-q", "-b", "feat/notes")
                head = repo.commit({NOTES: planted}, "docs: add notes")
                self.assertEqual(repo.cli("0" * 40, head)[0], expected)


class CleanRepoTests(unittest.TestCase):
    def test_todays_tree_scans_clean_as_one_new_commit(self):
        repo = Repo(self)
        listed = repo.git("-C", str(REPO_ROOT), "ls-files", "-z", "--cached", "--others", "--exclude-standard")
        names = sorted({name for name in listed.split("\0") if name and (REPO_ROOT / name).is_file()})
        self.assertIn(FIXTURE, names)
        self.assertIn(".github/scripts/tests/test_privacy_scan.py", names)
        repo.commit({name: (REPO_ROOT / name).read_bytes() for name in names}, "chore: import the tree")
        self.assertEqual(found(repo.scan()), set())


if __name__ == "__main__":
    unittest.main()
