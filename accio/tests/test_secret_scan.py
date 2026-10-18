"""S-011: secret patterns (ported from secret-guard) and the staged-file scan.

S-011/6: every fake key below is built at runtime by concatenation, so no key-shaped string sits in this file
(git-guardrails would rightly refuse to write one).
"""
import base64
import json
import pathlib
import stat
import tempfile
import unittest

from support import commit_all, git, init_repo, write

from accio_lib import secret_scan

BODY = "Ab3dE5gH7jK9mN1pQ3sT5vX7zB9dF1h"


def stripe_key():
    return "sk" + "_live_" + BODY[:24]


def aws_key():
    return "AK" + "IA" + "ABCDEFGH23456789"


def google_key():
    return "AI" + "za" + "Sy" + BODY + "ab"  # exactly 35 characters after the prefix


def jwt(role):
    def part(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return "e" + "y" + part({"alg": "HS256"})[2:] + "." + part({"role": role, "iss": "supabase"}) + "." + "s1gnatureXYZ123"


def db_url(rest, password="hunter" + "2"):
    return "postgres" + "://app:" + password + "@" + rest


class PatternTest(unittest.TestCase):
    def names(self, text):
        return [finding.name for finding in secret_scan.find_secrets(text)]

    def test_S_011_1_stripe_google_and_aws_keys_are_reported(self):
        self.assertEqual(self.names(f"key = '{stripe_key()}'"), ["Stripe secret key"])
        self.assertEqual(self.names(f"id = {aws_key()}"), ["AWS access key"])
        self.assertEqual(self.names(f"maps: {google_key()}"), ["Google API key"])

    def test_S_011_2_only_a_service_role_jwt_is_reported(self):
        self.assertEqual(self.names(f"anon = '{jwt('anon')}'"), [])
        self.assertEqual(self.names(f"admin = '{jwt('service_role')}'"), ["Supabase service_role key"])

    def test_S_011_3_local_database_urls_and_placeholders_pass(self):
        self.assertEqual(self.names("DATABASE_URL=postgres://app:" + "hunter2" + "@localhost:5432/app"), [])
        self.assertEqual(self.names("DATABASE_URL=postgres://app:${DB_PASSWORD}@db.prod.internal/app"), [])
        self.assertEqual(self.names("DATABASE_URL=postgres://app:" + "hunter2" + "@db.prod.internal/app"),
                         ["database password in a connection URL"])
        self.assertEqual(self.names("sk" + "_live_" + "x" * 24), [])
        self.assertEqual(self.names("AK" + "IA" + "IOSFODNN7" + "EXAMPLE"), [])

    def test_only_the_host_decides_a_database_url_is_local(self):
        for text in (db_url("db.prod.internal/app?fallback=@localhost:5432"), db_url("localhost.prod.io/app"),
                     db_url("localhost@db.prod.io/app")):
            self.assertEqual(self.names(text), ["database password in a connection URL"], text)

    def test_only_the_password_decides_a_database_url_is_a_placeholder(self):
        for text in (db_url("db.example-corp.io/app"), db_url("db.prod.io/app..."),
                     db_url("db.prod.io/app", "my" + "ExamplePass9")):
            self.assertEqual(self.names(text), ["database password in a connection URL"], text)
        for password in ("<password>", "xxxxxx", "EXAMPLE", "changeme"):
            self.assertEqual(self.names(db_url("db.prod.io/app", password)), [], password)
        self.assertEqual(self.names(db_url("db.example.com/app")), [])

    def test_S_011_4_a_finding_shows_only_a_prefix(self):
        key = stripe_key()
        finding = secret_scan.find_secrets(f"line one\nkey = '{key}'")[0]
        self.assertEqual(finding.line, 2)
        self.assertEqual(finding.preview, key[:secret_scan.VISIBLE_PREFIX] + "…")
        self.assertNotIn(key, secret_scan.describe("config.py", [finding]))

    def test_the_more_specific_pattern_names_an_overlap(self):
        anthropic = "sk" + "-ant-" + "api03-" + BODY + BODY
        self.assertEqual(self.names(anthropic), ["Anthropic API key"])

    def test_pgp_private_key_blocks_are_reported(self):
        self.assertEqual(self.names("-----BEGIN " + "PGP PRIVATE KEY BLOCK-----"), ["private key"])

    def test_a_google_key_ending_in_a_dash_is_reported(self):
        key = "AI" + "za" + "Sy" + BODY + "a-"
        self.assertEqual(self.names(f"key = '{key}'"), ["Google API key"])

    def test_kebab_case_names_are_not_mistaken_for_keys(self):
        self.assertEqual(self.names("ta" + "sk" + "-list-item-container-wrapper-header-title-block"), [])

    def test_env_files_are_secret_files_but_examples_are_not(self):
        self.assertTrue(secret_scan.is_secret_file("app/.env.local"))
        self.assertTrue(secret_scan.is_secret_file(".env"))
        self.assertFalse(secret_scan.is_secret_file(".env.example"))
        self.assertFalse(secret_scan.is_secret_file("docs/env.md"))

    def test_env_files_are_matched_in_any_case_and_common_spellings(self):
        for path in (".ENV", "App/.Env.Local", ".env-local", ".env_prod", "deploy/prod.env", "Docker.ENV",
                     "prod.env.local", "app.env.production"):
            self.assertTrue(secret_scan.is_secret_file(path), path)
        for path in (".ENV.EXAMPLE", "deploy/prod.env.Sample", ".env.local.template", "environment.py", ".envrc.md"):
            self.assertFalse(secret_scan.is_secret_file(path), path)


class StagedScanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = init_repo(pathlib.Path(self.tmp.name).resolve() / "app")

    def tearDown(self):
        self.tmp.cleanup()

    def test_S_011_5_built_in_patterns_scan_the_staged_content(self):
        write(self.repo / "config.py", f"KEY = '{stripe_key()}'\n")
        git(self.repo, "add", "config.py")
        write(self.repo / "config.py", "KEY = os.environ['KEY']\n")
        result = secret_scan.scan_staged(self.repo, gitleaks=None)
        self.assertEqual(result.tool, "built-in")
        self.assertEqual([(f.path, f.name) for f in result.findings], [("config.py", "Stripe secret key")])

    def test_S_011_5_a_staged_env_file_is_refused(self):
        write(self.repo / ".env", "HARMLESS=1\n")
        git(self.repo, "add", "-f", ".env")
        result = secret_scan.scan_staged(self.repo, gitleaks=None)
        self.assertEqual([f.name for f in result.findings], ["a file meant to hold secrets"])

    def test_S_011_5_clean_staged_files_pass(self):
        write(self.repo / "app.py", "print('hello')\n")
        git(self.repo, "add", "app.py")
        self.assertEqual(secret_scan.scan_staged(self.repo, gitleaks=None).findings, ())

    def fake_gitleaks(self, scan_exit, modern=True):
        """A stand-in gitleaks: `git --help` succeeds only when modern; the scan exits with scan_exit."""
        tool = pathlib.Path(self.tmp.name) / "gitleaks"
        log = pathlib.Path(self.tmp.name) / "args.txt"
        write(tool, "#!/bin/sh\n"
                    f"if [ \"$1 $2\" = 'git --help' ]; then exit {0 if modern else 1}; fi\n"
                    f"echo \"$@\" >> {log}\nexit {scan_exit}\n")
        tool.chmod(tool.stat().st_mode | stat.S_IEXEC)
        write(self.repo / "app.py", "print('hello')\n")
        git(self.repo, "add", "app.py")
        return str(tool), log

    def test_S_011_5_gitleaks_findings_use_their_own_exit_code(self):
        tool, log = self.fake_gitleaks(scan_exit=secret_scan.GITLEAKS_FOUND_EXIT)
        result = secret_scan.scan_staged(self.repo, gitleaks=tool)
        self.assertEqual(result.tool, "gitleaks+built-in")
        self.assertEqual(len(result.findings), 1)
        args = log.read_text().split()
        self.assertEqual(args[:3], ["git", "--pre-commit", "--staged"])
        self.assertIn("--exit-code", args)

    def test_S_011_5_old_gitleaks_uses_protect_and_a_clean_scan_passes(self):
        tool, log = self.fake_gitleaks(scan_exit=0, modern=False)
        self.assertEqual(secret_scan.scan_staged(self.repo, gitleaks=tool).findings, ())
        self.assertEqual(log.read_text().split()[:2], ["protect", "--staged"])

    def test_S_011_5_a_gitleaks_error_is_an_error_not_a_finding(self):
        tool, _ = self.fake_gitleaks(scan_exit=1)
        with self.assertRaises(secret_scan.SecretScanError):
            secret_scan.scan_staged(self.repo, gitleaks=tool)

    def test_with_gitleaks_installed_a_staged_env_file_is_still_refused(self):
        tool, _ = self.fake_gitleaks(scan_exit=0)
        write(self.repo / ".env", "DB_PASSWORD=hunter2\n")
        git(self.repo, "add", "-f", ".env")
        names = [f.name for f in secret_scan.scan_staged(self.repo, gitleaks=tool).findings]
        self.assertIn(secret_scan.SECRET_FILE_NAME, names)

    def test_with_gitleaks_installed_the_built_in_patterns_still_run(self):
        tool, _ = self.fake_gitleaks(scan_exit=0)
        write(self.repo / "conf.py", f"KEY = '{stripe_key()}'  # gitleaks:allow\n")
        git(self.repo, "add", "conf.py")
        self.assertIn("Stripe secret key", [f.name for f in secret_scan.scan_staged(self.repo, gitleaks=tool).findings])

    def test_a_file_named_like_a_stage_number_is_scanned_itself(self):
        write(self.repo / "config.py", "clean = True\n")
        commit_all(self.repo)
        write(self.repo / "0:config.py", f"KEY = '{stripe_key()}'\n")
        git(self.repo, "add", "0:config.py")
        self.assertEqual([f.path for f in secret_scan.scan_staged(self.repo, gitleaks=None).findings], ["0:config.py"])

    def test_a_symlink_turned_into_a_file_is_scanned(self):
        (self.repo / "conf.py").symlink_to("README.md")
        commit_all(self.repo)
        (self.repo / "conf.py").unlink()
        write(self.repo / "conf.py", f"KEY = '{stripe_key()}'\n")
        git(self.repo, "add", "conf.py")
        self.assertEqual([f.path for f in secret_scan.scan_staged(self.repo, gitleaks=None).findings], ["conf.py"])

    def test_utf16_and_nul_bearing_files_are_scanned(self):
        (self.repo / "setup.ps1").write_bytes(("$key = '" + stripe_key() + "'\n").encode("utf-16"))
        (self.repo / "data.txt").write_bytes(b"\0\0head\n" + ("KEY=" + stripe_key()).encode())
        git(self.repo, "add", "setup.ps1", "data.txt")
        paths = sorted(f.path for f in secret_scan.scan_staged(self.repo, gitleaks=None).findings)
        self.assertEqual(paths, ["data.txt", "setup.ps1"])

    def test_a_staged_submodule_is_skipped_without_a_crash(self):
        library = init_repo(pathlib.Path(self.tmp.name).resolve() / "lib")
        git(self.repo, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(library), "sub")
        self.assertEqual(secret_scan.scan_staged(self.repo, gitleaks=None).findings, ())

    def test_binary_staged_files_are_scanned_without_a_crash(self):
        (self.repo / "logo.png").write_bytes(bytes(range(256)) * 4)
        git(self.repo, "add", "logo.png")
        self.assertEqual(secret_scan.scan_staged(self.repo, gitleaks=None).findings, ())

    def test_a_deleted_file_is_not_scanned(self):
        write(self.repo / "old.py", "x = 1\n")
        commit_all(self.repo)
        git(self.repo, "rm", "-q", "old.py")
        self.assertEqual(secret_scan.scan_staged(self.repo, gitleaks=None).findings, ())


if __name__ == "__main__":
    unittest.main()
