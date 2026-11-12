import argparse
import hashlib
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import PurePosixPath

SIZE_LIMIT_BYTES = 100_000
SIZE_EXEMPT = {"backend/uv.lock", "frontend/pnpm-lock.yaml"}
PINNED_IMAGES = {
    "backend/tests/fixtures/astronaut.jpg": "78831fd8952dbf1cf60e50d6749ac6af8fcd32f0056197b855df36404f889e48"
}
DATA_SUFFIXES = {
    ".npz",
    ".npy",
    ".csv",
    ".mp4",
    ".mov",
    ".webm",
    ".wav",
    ".task",
    ".tflite",
    ".onnx",
}
IMAGE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".heic",
    ".heif",
    ".avif",
    ".bmp",
    ".tif",
    ".tiff",
    ".ico",
}
ENV_EXAMPLE = ".env.example"
DEFAULT_BRANCHES = ("origin/master", "master")
ZERO_SHA = re.compile(r"^0+$")
CONTENT_PATTERNS = [
    ("path", re.compile(r"\\?/user[s]\\?/[^/\s\\]+", re.IGNORECASE)),
    ("path", re.compile(r"-User[s]-[^-\s]+-")),
    ("path", re.compile(r"/hom[e]/(?!runner\b)")),
    ("path", re.compile(r"/privat[e]/(?:tmp|var)/")),
    ("path", re.compile(r"/va[r]/folders/")),
    ("path", re.compile(r"/Volume[s]/")),
    ("path", re.compile(r"\bclaude-\d+")),
    ("path", re.compile(r"personal(?:[ ]|\\[ ]|%20)projects", re.IGNORECASE)),
    ("path", re.compile(r"C:\\User[s]\\")),
    (
        "private IP",
        re.compile(r"(?<![\d.])(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}(?!\d|\.\d)"),
    ),
    ("private IP", re.compile(r"(?<![0-9a-f:])f[d][0-9a-f]{2}:[0-9a-f]{0,4}:", re.IGNORECASE)),
    ("link-local IP", re.compile(r"(?<![\d.])169\.254\.\d{1,3}\.\d{1,3}(?!\d|\.\d)")),
    ("link-local IP", re.compile(r"(?<![0-9a-f:])f[e][89ab][0-9a-f]:[0-9a-f]{0,4}:", re.IGNORECASE)),
    (
        "MAC address",
        re.compile(r"(?<![0-9A-Fa-f:-])[0-9A-Fa-f]{2}([:-])(?:[0-9A-Fa-f]{2}\1){4}[0-9A-Fa-f]{2}(?![0-9A-Fa-f:-])"),
    ),
    ("key", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("key", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}")),
    ("key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("key", re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}")),
    ("key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("key", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("key", re.compile(r"-----BEGIN[A-Z ]*PRIVATE KEY")),
    ("key", re.compile(r"\bGH_TOKEN\s*[=:]")),
]
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
WEB_MERGE_EMAIL = "noreply@github.com"
USERS_NOREPLY_SUFFIX = "@users.noreply.github.com"
DECORATOR_DOMAIN_PREFIX = "pytest."
ATTRIBUTES_FILE = ".gitattributes"
BINARY_FILE = "binary file"
NUL = b"\0"
GITLINK_MODE = "160000"
FILE_NAME = "a file name"
DIFF_OPTIONS = (
    "-U0",
    "--text",
    "--no-color",
    "--no-ext-diff",
    "--no-textconv",
    "--no-renames",
    "--src-prefix=a/",
    "--dst-prefix=b/",
)


class ScanError(Exception):
    pass


@dataclass(frozen=True)
class Finding:
    kind: str
    path: str

    def line(self) -> str:
        return f"{self.kind}: {self.path}"


@dataclass(frozen=True)
class Change:
    status: str
    path: str
    blob: str
    mode: str = ""


class Git:
    def __init__(self, repo: str) -> None:
        self.repo = repo

    def output(self, *args: str) -> bytes:
        argv = ["git", "-C", self.repo, "-c", "core.quotepath=false", *args]
        try:
            done = subprocess.run(argv, capture_output=True, check=False)
        except OSError as error:
            raise ScanError(f"git {args[0]} could not start: {error.strerror}") from error
        if done.returncode != 0:
            detail = done.stderr.decode(errors="replace").strip().splitlines()
            raise ScanError(f"git {args[0]} failed: {detail[-1] if detail else done.returncode}")
        return done.stdout

    def text(self, *args: str) -> str:
        return self.output(*args).decode(errors="replace")

    def succeeds(self, *args: str) -> bool:
        argv = ["git", "-C", self.repo, *args]
        try:
            return subprocess.run(argv, capture_output=True, check=False).returncode == 0
        except OSError as error:
            raise ScanError(f"git {args[0]} could not start: {error.strerror}") from error


def text_email_allowed(email: str) -> bool:
    lowered = email.lower()
    domain = lowered.partition("@")[2]
    return (
        lowered == WEB_MERGE_EMAIL
        or lowered.endswith(USERS_NOREPLY_SUFFIX)
        or domain.startswith(DECORATOR_DOMAIN_PREFIX)
    )


def role_email_allowed(email: str, authors: set[str]) -> bool:
    return email.lower() in authors or text_email_allowed(email)


def text_findings(text: str, where: str) -> list[Finding]:
    findings = [Finding(kind, where) for kind, pattern in CONTENT_PATTERNS if pattern.search(text)]
    if any(not text_email_allowed(match.group(0)) for match in EMAIL.finditer(text)):
        findings.append(Finding("email", where))
    return findings


def place(path: str) -> str:
    return FILE_NAME if text_findings(path, FILE_NAME) else path


def is_env_file(name: str) -> bool:
    return (name == ".env" or name.startswith(".env.")) and name != ENV_EXAMPLE


def is_pinned(change: Change, data: bytes) -> bool:
    expected = PINNED_IMAGES.get(change.path)
    return expected is not None and hashlib.sha256(data).hexdigest() == expected


def type_findings(change: Change, data: bytes, where: str) -> list[Finding]:
    path = PurePosixPath(change.path)
    suffix = path.suffix.lower()
    if is_env_file(path.name):
        return [Finding("env file", where)]
    if suffix in DATA_SUFFIXES:
        return [Finding("data file", where)]
    if suffix in IMAGE_SUFFIXES:
        return [] if is_pinned(change, data) else [Finding("image", where)]
    if change.status == "A" and change.path not in SIZE_EXEMPT and len(data) > SIZE_LIMIT_BYTES:
        return [Finding("large file", where)]
    return []


def file_findings(change: Change, data: bytes) -> list[Finding]:
    if PurePosixPath(change.path).name == ATTRIBUTES_FILE:
        return [Finding("attributes file change", place(change.path))]
    if change.status == "D":
        return []
    where = place(change.path)
    findings = type_findings(change, data, where)
    if NUL in data and not is_pinned(change, data):
        findings.append(Finding(BINARY_FILE, where))
    return findings


def name_findings(changes: list[Change]) -> list[Finding]:
    findings = []
    for change in changes:
        if change.status != "D":
            findings += text_findings(change.path, FILE_NAME)
    return findings


def added_lines(patch: str) -> dict[str, list[str]]:
    lines: dict[str, list[str]] = {}
    current: str | None = None
    in_hunk = False
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            current, in_hunk = None, False
        elif not in_hunk and line.startswith("+++ "):
            target = line[4:].rstrip("\t")
            current = target[2:] if target.startswith("b/") else None
        elif line.startswith("@@"):
            in_hunk = True
        elif in_hunk and current is not None and line.startswith("+"):
            lines.setdefault(current, []).append(line[1:])
    return lines


def raw_changes(raw: bytes) -> list[Change]:
    fields = raw.decode(errors="replace").split("\0")
    changes = []
    for index in range(0, len(fields) - 1, 2):
        meta, path = fields[index], fields[index + 1]
        parts = meta.lstrip(":").split()
        if len(parts) >= 5:
            changes.append(Change(parts[4][0], path, parts[3], parts[1]))
    return changes


def blob_content(git: Git, change: Change) -> bytes:
    if change.status == "D" or change.mode == GITLINK_MODE:
        return b""
    return git.output("cat-file", "blob", change.blob)


def commit_details(git: Git, sha: str) -> tuple[list[str], str, str, str]:
    meta = git.text("show", "-s", "--format=%P%x00%ae%x00%ce%x00%B", sha).split("\0", 3)
    if len(meta) < 4:
        raise ScanError(f"git show gave no details for commit {sha[:7]}")
    parents, author, committer, message = meta
    return parents.split(), author, committer, message


def commit_findings(git: Git, sha: str, allowed: set[str]) -> list[Finding]:
    short = sha[:7]
    parents, author, committer, message = commit_details(git, sha)
    findings = text_findings(message, f"commit {short} message")
    for role, email in (("author", author), ("committer", committer)):
        if email and not role_email_allowed(email, allowed):
            findings.append(Finding("email", f"commit {short} {role}"))
    trees = [parents[0], sha] if parents else ["--root", sha]
    changes = raw_changes(git.output("diff-tree", "-r", "-z", "--no-commit-id", "--raw", "--no-renames", *trees))
    findings += name_findings(changes)
    for change in changes:
        findings += file_findings(change, blob_content(git, change))
    patch = git.text("diff-tree", "-p", "--no-commit-id", *DIFF_OPTIONS, *trees)
    for path, lines in added_lines(patch).items():
        findings += text_findings("\n".join(lines), place(path))
    return findings


def history_emails(git: Git, start: str | None) -> set[str]:
    if start is None:
        return set()
    listed = git.text("log", "--format=%ae%n%ce", start)
    return {line.strip().lower() for line in listed.splitlines() if line.strip()}


def merge_base_with_default(git: Git, head: str) -> str:
    for branch in DEFAULT_BRANCHES:
        if git.succeeds("rev-parse", "--verify", "--quiet", f"{branch}^{{commit}}"):
            return git.text("merge-base", branch, head).strip()
    raise ScanError("no base commit and no master branch to measure a new branch from")


def resolve_base(git: Git, base: str, head: str) -> str:
    if ZERO_SHA.match(base) or not git.succeeds("cat-file", "-e", f"{base}^{{commit}}"):
        return merge_base_with_default(git, head)
    return base


def unique(findings: list[Finding]) -> list[Finding]:
    return list(dict.fromkeys(findings))


def scan_range(repo: str, base: str, head: str) -> list[Finding]:
    git = Git(repo)
    start = resolve_base(git, base, head)
    allowed = history_emails(git, start)
    commits = git.text("rev-list", "--reverse", f"{start}..{head}").split()
    findings: list[Finding] = []
    for sha in commits:
        findings += commit_findings(git, sha, allowed)
    return unique(findings)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="privacy_scan")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        findings = scan_range(args.repo, args.base, args.head)
    except ScanError as error:
        print(f"privacy scan could not run: {error}", file=sys.stderr)
        return 2
    for finding in findings:
        print(finding.line())
    if findings:
        print(f"privacy scan: {len(findings)} finding(s); remove them or extend the allowlist with a reviewed reason")
        return 1
    print("privacy scan: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
