import contextlib
import gzip
import io
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import privacy_scan

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = "backend/tests/fixtures/astronaut.jpg"


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
MISSING_HEAD = "0123456789abcdef0123456789abcdef01234567"


class Repo:
    def __init__(self, case):
        self.root = Path(tempfile.mkdtemp(prefix="privacyscan-"))
        case.addCleanup(shutil.rmtree, self.root, True)
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
