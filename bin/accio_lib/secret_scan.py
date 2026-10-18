"""Find secrets in text and in staged files (DESIGN § 6, decision 004).

The patterns are ported from the user's secret-guard mod (`claude-mods/secret-guard/hooks/patterns.ts`):
- formats that are a live credential on sight, most specific first (Anthropic and OpenRouter before OpenAI)
- a JWT counts only when its role is `service_role`; a database URL only when its host isn't local and its
  password isn't a placeholder (each judged on its own part of the URL); an `sk-` match only when it has a
  random-looking body (not a kebab-case name)
- documented examples (EXAMPLE, xxxxxx, your_api_key, <...>) are skipped
- a finding shows only the first VISIBLE_PREFIX characters, never the secret

Deliberate changes from secret-guard (worth porting back): armored PGP blocks (`PRIVATE KEY BLOCK`) count; a
Google key may end in `-` (the source's closing `\b` missed about 1 key in 64); a database URL's host and password
are checked on their own (a `@localhost:` or `example` elsewhere in the URL no longer exempts it); and `.env` files
match in any case and as `.env-x`, `.env_x`, `x.env` and `x.env.y`. The host is everything up to the path, so
`localhost@db.prod.io` isn't taken for local (fails closed).

The staged scan reads each staged blob by id (so odd names like `0:config.py` and type changes are covered), skips
only deletions, submodules and symlinks, and always runs these patterns and the `.env` refusal; gitleaks, when
installed, adds its own rules on top.
"""
import base64
import binascii
import collections
import dataclasses
import json
import re
import shutil
import subprocess

VISIBLE_PREFIX = 6
KEY_RUN = 8
MAX_KEY_BODY = 16384  # the body up to END belongs to the key, so a new body under an old header is new
GITLEAKS_FOUND_EXIT = 99
FILE_MODES = ("100644", "100755")
OUTPUT_TAIL_CHARS = 2000
# A database host no real credential reaches: this machine, or an RFC 2606 documentation domain.
UNREACHABLE_HOST = re.compile(
    r"(?:localhost|127\.0\.0\.1|0\.0\.0\.0|host\.docker\.internal|(?:[\w-]+\.)*example\.(?:com|org|net))(?::\d+)?",
    re.I)
PASSWORD_PLACEHOLDER = re.compile(r"\$\{.*\}|\[.*\]|<.*>|\*+|x+|password|postgres|pass|example|changeme", re.I)
PLACEHOLDER = re.compile(r"x{6,}|EXAMPLE|your[_-]?(?:api[_-]?)?key|<[^>]*>|\.\.\.", re.I)
SECRET_FILE = re.compile(r"(^|/)[^/]*\.env([._-][^/]*)?$", re.I)
TEMPLATE_FILE = re.compile(r"\.(example|sample|template|dist)$", re.I)
SECRET_FILE_NAME = "a file meant to hold secrets"
AUTO = object()


class SecretScanError(Exception):
    """The scan itself failed, written for the user."""


@dataclasses.dataclass(frozen=True)
class Finding:
    name: str
    line: int
    preview: str
    path: str = ""


@dataclasses.dataclass(frozen=True)
class ScanResult:
    tool: str
    findings: tuple
    output: str = ""


def _has_random_body(match):
    return any(len(part) >= KEY_RUN and re.search(r"[A-Z0-9]", part) for part in re.split(r"[-_]", match.group(0)))


def jwt_role(token):
    """The `role` claim of a JWT's payload, or None when it doesn't decode."""
    parts = token.split(".")
    if len(parts) < 2:
        return None
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except (binascii.Error, ValueError, UnicodeError):
        return None
    role = claims.get("role") if isinstance(claims, dict) else None
    return role if isinstance(role, str) else None


def _db_password_is_secret(match):
    is_reachable = not UNREACHABLE_HOST.fullmatch(match.group("host"))
    return is_reachable and not PASSWORD_PLACEHOLDER.fullmatch(match.group("secret"))


def _is_placeholder(match):
    """A documented example key. A URL's password is judged whole by PASSWORD_PLACEHOLDER instead, so a real
    password that merely contains `example` still counts; a private key never is one (its body is random text)."""
    judged_elsewhere = {"secret", "pem_body"} & set(match.re.groupindex)
    return not judged_elsewhere and bool(PLACEHOLDER.search(match.group(0)))


PATTERNS = (
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----"
                                r"(?P<pem_body>(?:(?!-----END )[\s\S]){0,%d}-----END [A-Z ]{0,40}-----)?" % MAX_KEY_BODY),
     None),
    ("Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), _has_random_body),
    ("OpenRouter API key", re.compile(r"sk-or-(?:v1-)?[A-Za-z0-9]{32,}"), _has_random_body),
    ("OpenAI API key", re.compile(r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}"), _has_random_body),
    ("Stripe secret key", re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}"), None),
    ("Supabase secret key", re.compile(r"\bsb_secret_[A-Za-z0-9_-]{16,}"), None),
    ("Supabase service_role key", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
     lambda match: jwt_role(match.group(0)) == "service_role"),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), None),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})"), None),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), None),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}(?![0-9A-Za-z_-])"), None),
    ("database password in a connection URL",
     re.compile(r"\bpostgres(?:ql)?://[^:\s/@]+:(?P<secret>[^@\s]+)@(?P<host>[^\s/?#'\"`]+)[^\s'\"`]*"),
     _db_password_is_secret),
)


def is_secret_file(path):
    """`.env`, `.env.local`, `.env-prod`, `prod.env.local`, in any case, but not the committed `.env.example` and
    kin."""
    return bool(SECRET_FILE.search(path)) and not TEMPLATE_FILE.search(path)


def mask(secret):
    return f"{secret[:VISIBLE_PREFIX]}…"


def _matches(text):
    """(start, name, value) of every secret; an earlier pattern wins an overlap."""
    matches = []
    for name, pattern, is_secret in PATTERNS:
        for match in pattern.finditer(text):
            if _is_placeholder(match) or (is_secret and not is_secret(match)):
                continue
            matches.append((match.start(), match.end(), name, match.group(0)))
    kept = []
    for start, end, name, value in matches:
        if not any(start < k_end and k_start < end for k_start, k_end, _, _ in kept):
            kept.append((start, end, name, value))
    return tuple((start, name, value) for start, _, name, value in kept)


def secret_values(text):
    """How often each raw secret occurs in `text`, only for comparing two texts; never print them."""
    return collections.Counter(value for _, _, value in _matches(text))


def find_secrets(text, path="", known=None):
    """Every recognisable secret, with its line and a masked preview. `known` counts occurrences to skip (a value
    already in the file before an edit); one more occurrence than known is still found, so a second private key
    under the same header counts."""
    remaining = collections.Counter(known or {})
    findings = []
    for start, name, value in _matches(text):
        if remaining[value] > 0:
            remaining[value] -= 1
            continue
        findings.append(Finding(name=name, line=text.count("\n", 0, start) + 1, preview=mask(value), path=path))
    return tuple(findings)


def describe(path, findings):
    listed = "; ".join(f"{f.name} on line {f.line} ({f.preview})" for f in findings)
    return (f"accio: {path} contains {listed}. Read the value from an environment variable instead, and keep the "
            "real value in a gitignored .env file.")


def _git_bytes(repo, *args):
    try:
        result = subprocess.run(["git", *args], cwd=repo, capture_output=True, check=False)
    except OSError as error:
        raise SecretScanError(f"git could not run in {repo}: {error}") from error
    if result.returncode != 0:
        raise SecretScanError(f"git {' '.join(args)} failed: {result.stderr.decode('utf-8', 'replace').strip()}")
    return result.stdout


def _run_tool(command, repo):
    try:
        return subprocess.run(command, cwd=repo, capture_output=True, check=False)
    except OSError as error:
        raise SecretScanError(f"{command[0]} could not run: {error}") from error


def _scan_with_gitleaks(repo, gitleaks):
    """gitleaks on the staged changes; only GITLEAKS_FOUND_EXIT means findings, any other failure is an error."""
    modern = _run_tool([gitleaks, "git", "--help"], repo).returncode == 0
    args = ["git", "--pre-commit", "--staged"] if modern else ["protect", "--staged"]
    command = [gitleaks, *args, "--redact", "--verbose", "--no-banner", "--exit-code", str(GITLEAKS_FOUND_EXIT)]
    result = _run_tool(command, repo)
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")[-OUTPUT_TAIL_CHARS:]
    if result.returncode == 0:
        return (), output
    if result.returncode == GITLEAKS_FOUND_EXIT:
        return (Finding("gitleaks found a secret (see its redacted output)", 0, ""),), output
    raise SecretScanError(f"gitleaks failed (exit {result.returncode}): {output.strip()}")


def _staged_blobs(repo):
    """(path, blob id) for every staged file that isn't a deletion, a submodule or a symlink."""
    raw = _git_bytes(repo, "diff", "--cached", "--raw", "-z", "--no-renames", "--no-abbrev", "--diff-filter=d")
    fields = [part for part in raw.decode("utf-8", errors="surrogateescape").split("\0") if part]
    blobs = []
    for header, path in zip(fields[0::2], fields[1::2]):
        _, new_mode, _, new_sha, _ = header.lstrip(":").split(" ", 4)
        if new_mode in FILE_MODES:
            blobs.append((path, new_sha))
    return tuple(blobs)


def _decode(content):
    """Text for the ASCII patterns: UTF-16 by its byte-order mark, else UTF-8 with bad bytes replaced."""
    if content[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return content.decode("utf-16", errors="replace")
    return content.decode("utf-8", errors="replace")


def _scan_built_in(repo):
    findings = []
    for path, blob in _staged_blobs(repo):
        if is_secret_file(path):
            findings.append(Finding(SECRET_FILE_NAME, 1, "", path))
            continue
        findings.extend(find_secrets(_decode(_git_bytes(repo, "cat-file", "blob", blob)), path))
    return tuple(findings)


def scan_staged(repo, gitleaks=AUTO):
    """Scan what is about to be committed. The built-in patterns and the `.env` refusal always run (an inline
    `gitleaks:allow` or a repo allowlist can't switch them off); gitleaks adds its rules when installed."""
    tool = shutil.which("gitleaks") if gitleaks is AUTO else gitleaks
    built_in = _scan_built_in(repo)
    if not tool:
        return ScanResult("built-in", built_in)
    extra, output = _scan_with_gitleaks(repo, tool)
    return ScanResult("gitleaks+built-in", built_in + extra, output)
