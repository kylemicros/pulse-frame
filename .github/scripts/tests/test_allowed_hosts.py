import re
import unittest
from pathlib import Path

import privacy_scan

REPO_ROOT = Path(__file__).resolve().parents[3]
ALLOWED_HOSTS_FILE = REPO_ROOT / ".github" / "allowed-hosts.txt"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
GITHUB = "github.com"
PYPI = "pypi.org"
HOST_FORM = re.compile(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?")


def joined(*parts):
    return "".join(parts)


def allowed_lines(case):
    case.assertTrue(ALLOWED_HOSTS_FILE.is_file(), f"{ALLOWED_HOSTS_FILE.name} is missing from .github")
    return ALLOWED_HOSTS_FILE.read_bytes().split(b"\n")


class AllowedHostsFileTests(unittest.TestCase):
    def test_allowed_hosts_file_exists_with_unique_ascii_lines(self):
        lines = allowed_lines(self)
        self.assertEqual(lines[-1], b"", "the file must end with one newline")
        hosts = lines[:-1]
        self.assertTrue(hosts)
        self.assertEqual([line for line in hosts if not line.isascii()], [])
        self.assertEqual(sorted({line for line in hosts if hosts.count(line) > 1}), [])

    def test_each_line_is_one_lower_case_host_and_github_and_pypi_are_listed(self):
        hosts = [line.decode("ascii") for line in allowed_lines(self)[:-1]]
        self.assertEqual([host for host in hosts if HOST_FORM.fullmatch(host) is None], [])
        self.assertIn(GITHUB, hosts)
        self.assertIn(PYPI, hosts)
        self.assertEqual([host for host in hosts if "cloudns" in host], [])


class WorkflowHostTests(unittest.TestCase):
    def test_every_url_host_in_the_workflows_is_on_the_allowlist_or_exempt(self):
        allowed = frozenset(line.decode("ascii") for line in allowed_lines(self)[:-1])
        seen = 0
        findings = []
        for workflow in sorted(WORKFLOWS.glob("*.yml")):
            for number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), start=1):
                seen += len(privacy_scan.scheme_hosts(line))
                findings += privacy_scan.host_findings(line, f"{workflow.name}:{number}", allowed)
        self.assertTrue(seen, "no URL host found in the workflows")
        self.assertEqual(findings, [])

    def test_workflow_line_with_postgres_on_a_special_scheme_is_flagged(self):
        allowed = frozenset(line.decode("ascii") for line in allowed_lines(self)[:-1])
        line = joined("    image: ", "https", "://", "postgres", ":5432/x")
        findings = privacy_scan.host_findings(line, "ci.yml:1", allowed)
        self.assertEqual([finding.kind for finding in findings], [privacy_scan.UNTRUSTED_HOST])


if __name__ == "__main__":
    unittest.main()
