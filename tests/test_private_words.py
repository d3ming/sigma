"""The private-word guard (scripts/private_words.py). Expected values are the rules in AGENTS.md: the list is committed as
salted hashes, matches are whole words, a hit never prints the word, and a missing list fails instead of passing."""
import subprocess
import sys
from pathlib import Path

from tests.helpers import private_words as pw

ROOT = Path(__file__).parent.parent
WORD = "forbidden-marker"


def repo(tmp_path, words=(WORD,), list_name=".private-words.sha256"):
    """A scratch git repo holding a copy of the guard and, unless words is None, a hash list of the given words."""
    (tmp_path / "scripts").mkdir()
    for name in ("private_words.py", "private-words.sh"):
        (tmp_path / "scripts" / name).write_bytes((ROOT / "scripts" / name).read_bytes())
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    if words is not None:
        salt = "0123456789abcdef"
        hashes = sorted(pw.digest(salt, w) for w in words)
        (tmp_path / list_name).write_text("\n".join([f"salt {salt}", *hashes]) + "\n")
    return tmp_path


def run(root, *args):
    return subprocess.run([sys.executable, "scripts/private_words.py", *args], cwd=root, capture_output=True, text=True)


def stage(root, name, text):
    (root / name).write_text(text)
    subprocess.run(["git", "add", name], cwd=root, check=True)


def test_checks_the_index_instead_of_the_working_copy(tmp_path):
    """Failure seen in PR review: a clean working copy hid forbidden text already staged for commit."""
    root = repo(tmp_path)
    stage(root, "sample.txt", f"{WORD}\n")
    (root / "sample.txt").write_text("clean\n")
    assert run(root).returncode == 1
    stage(root, "sample.txt", "clean\n")
    (root / "sample.txt").write_text(f"{WORD}\n")
    assert run(root).returncode == 0


def test_a_hit_names_the_file_and_line_and_never_the_word(tmp_path):
    root = repo(tmp_path)
    stage(root, "notes.md", f"fine\nsee {WORD.upper()} here\n")
    r = run(root)
    assert r.returncode == 1 and "notes.md:2" in r.stderr and WORD not in r.stderr.lower()


def test_matches_whole_words_and_phrases_only(tmp_path):
    root = repo(tmp_path, words=("zed", "ada lovelace"))
    stage(root, "a.txt", "zeds zedx azed\n")  # parts of longer words are not the word
    assert run(root).returncode == 0
    for text in ("@zed on a profile", "https://zed.example/page", "Ada  Lovelace wrote it", "ZED_"):
        stage(root, "a.txt", text + "\n")
        assert (run(root).returncode == 1) == (text != "ZED_"), text  # an underscore joins words: ZED_ is one token
    stage(root, "a.txt", "Ada\nLovelace wrote it\n")
    r = run(root)
    assert r.returncode == 1 and "a.txt:1" in r.stderr and "Ada" not in r.stderr


def test_a_file_name_is_checked_too(tmp_path):
    root = repo(tmp_path)
    stage(root, f"{WORD}.txt", "clean\n")
    assert run(root).returncode == 1


def test_a_missing_or_empty_list_fails_closed(tmp_path):
    root = repo(tmp_path, words=None)
    stage(root, "a.txt", "clean\n")
    r = run(root)
    assert r.returncode != 0 and "fails closed" in r.stderr
    (root / ".private-words.sha256").write_text("salt abc\n")  # a salt and no hashes is also not a guard
    assert run(root).returncode != 0
    assert subprocess.run(["sh", "scripts/private-words.sh"], cwd=root, capture_output=True).returncode != 0


def test_a_commit_message_a_log_range_and_pr_text_are_checked(tmp_path):
    root = repo(tmp_path)
    msg = root / "MSG"
    msg.write_text(f"feat: change\n\n{WORD} did it\n# a comment line is dropped by git\n")
    assert run(root, "--msg", str(msg)).returncode == 1
    msg.write_text(f"feat: change\n\n# {WORD}\n")
    assert run(root, "--msg", str(msg)).returncode == 0
    git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], cwd=root, check=True,
                                    capture_output=True)
    git("commit", "-q", "--allow-empty", "-m", "base")
    git("commit", "-q", "--allow-empty", "-m", f"fix: {WORD}")
    assert run(root, "--log", "HEAD~1..HEAD").returncode == 1
    assert run(root, "--log", "HEAD~1").returncode == 0
    env = {"PATH": "/usr/bin:/bin", "TITLE": f"Fix for {WORD}", "BODY": "clean"}
    kw = dict(cwd=root, capture_output=True, text=True, env=env)
    assert subprocess.run([sys.executable, "scripts/private_words.py", "--env", "TITLE"], **kw).returncode == 1
    assert subprocess.run([sys.executable, "scripts/private_words.py", "--env", "BODY"], **kw).returncode == 0


def test_the_committed_list_loads():
    salt, hashes = pw.load(local=None)
    assert len(salt) >= 16 and len(hashes) >= 1


AT = "@"  # addresses and numbers are built at run time, so this file holds none
TAIL = "53" + "09"


def test_any_personal_email_or_phone_is_flagged_without_a_list_entry(tmp_path):
    """The owner's rule: a personal email or phone never ships, listed or not. The hit names the kind, never the value."""
    root = repo(tmp_path)
    stage(root, "page.md", f"mail anyone{AT}corp.org\ncall (212) 867-{TAIL} or +1212867{TAIL}\ncall me at 2128675309\nphone: 2128675309\n{{\"phone\":\"4158675309\"}}\nrevenue 4155551212\nID 9876543210\nfine\n")
    r = run(root)
    assert r.returncode == 1
    assert all(f"page.md:{line} (" in r.stderr for line in (1, 2, 3, 4, 5))
    assert all(f"page.md:{line}" not in r.stderr for line in (6, 7, 8))
    assert "corp.org" not in r.stderr and "867" not in r.stderr and "2128675309" not in r.stderr


def test_reserved_example_addresses_and_fictional_numbers_are_allowed(tmp_path):
    root = repo(tmp_path)
    allowed = [f"a{AT}example.com", f"a{AT}b.example.org", f"a{AT}host.invalid", f"a{AT}x.test", f"noreply{AT}github.com",
               f"123+me{AT}users.noreply.github.com", f"git{AT}github.com", "call 212-555-0142", "(415) 555-0100", "build 2026-10-30 12:00"]
    stage(root, "ok.md", "\n".join(allowed) + "\n")
    assert run(root).returncode == 0
    stage(root, "bad.md", f"a{AT}example.com.evil.io\n")
    assert run(root).returncode == 1


def test_a_directory_of_built_output_is_checked(tmp_path):
    root = repo(tmp_path, words=(WORD, "sigma.example"))
    out = tmp_path / "site"
    (out / "static").mkdir(parents=True)
    (out / "static" / "index.html").write_text(f"<p>{WORD}</p>\n<a href='mailto:me{AT}corp.org'>mail</a>\n")
    (out / "static" / "logo.bin").write_bytes(b"\0\1" + f"x{AT}corp.org".encode())  # binary files are skipped
    r = run(root, "--path", str(out))
    assert r.returncode == 1 and "static/index.html:1" in r.stderr and "static/index.html:2 (email address)" in r.stderr
    assert "logo.bin" not in r.stderr and WORD not in r.stderr
    page = out / "static" / "index.html"
    page.write_text("<a href='https://sigma.example/research'>Sigma</a>\n")
    assert run(root, "--path", str(out), "--public-origin", "https://sigma.example/").returncode == 0
    for value in ("sigma.example", "https://sigma.example/research/forbidden-marker",
                  "https://sigma.example/?q=forbidden-marker", "https://sigma.example.evil/research"):
        page.write_text(value + "\n")
        assert run(root, "--path", str(out), "--public-origin", "https://sigma.example").returncode == 1, value
    page.write_text("https://sigma.example/research\n")
    for origin in ("https://sigma.example/research", "https://user@sigma.example", "https://sigma.example/?q=1",
                   "https://sigma.example bad"):
        assert run(root, "--path", str(out), "--public-origin", origin).returncode != 0, origin
    assert run(root, "--public-origin", "https://sigma.example").returncode != 0
    page.write_text("<p>clean</p>\n")
    assert run(root, "--path", str(out)).returncode == 0


def test_a_listed_phone_number_matches_however_a_page_prints_it():
    number = "415 555 " + "0187"
    forms = pw.phone_variants(number)
    assert set(forms) == {number, "1 " + number, number.replace(" ", ""), "1" + number.replace(" ", "")}
    salt, hashes = "s", {pw.digest("s", f) for f in forms}
    for text in ("call (415) 555-0187", "+1 415.555.0187", "4155550187", "1-415-555-0187"):
        assert pw.hits_in_line(text, salt, hashes), text
    assert pw.phone_variants("a plain phrase") == ["a plain phrase"]
