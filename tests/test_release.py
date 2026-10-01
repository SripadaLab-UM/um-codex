"""The release workflow's shape (the signing key is in one small job only), the tag
check, and scripts/build-release.sh's files, signed with a throwaway key and
installed by `um-codex update` from a stand-in for GitHub.

Adapted from IHS DataLab's backend/tests/test_release_workflow.py at 6b6fdca.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.fake_github import FakeGitHub, FakeRelease
from umcodex import signing
from umcodex.releases import ReleaseSource, parse_sums
from umcodex.update import Layout, Updater, check_images, check_requirements

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
CI = ROOT / ".github" / "workflows" / "ci.yml"
AGENT = "ghcr.io/sripadalab-um/um-codex-agent@sha256:" + "a" * 64


def jobs() -> dict:
    parsed = yaml.safe_load(WORKFLOW.read_text())
    assert isinstance(parsed, dict) and isinstance(parsed.get("jobs"), dict)
    return parsed["jobs"]


def environment(job: dict) -> str | None:
    value = job.get("environment")
    return value.get("name") if isinstance(value, dict) else value


def test_it_runs_on_version_tags_only():
    parsed = yaml.safe_load(WORKFLOW.read_text())
    on = parsed.get("on", parsed.get(True))  # YAML reads a bare `on` as true
    assert on == {"push": {"tags": ["v*"]}}
    assert parsed["permissions"] == {"contents": "read"}


def test_only_the_sign_job_is_in_the_release_environment():
    found = {name for name, job in jobs().items() if environment(job) == "release"}
    assert found == {"sign"}


def test_only_the_sign_job_reads_the_signing_key():
    for name, job in jobs().items():
        text = yaml.safe_dump(job)
        assert ("RELEASE_SIGNING_KEY" in text and "secrets." in text) == (name == "sign"), name


def test_the_sign_job_runs_no_build_and_no_docker():
    sign = jobs()["sign"]
    assert sign["needs"] == "package"
    text = yaml.safe_dump(sign["steps"])
    for forbidden in ("npm", "setup-node", "build-release", "uv build", "docker", "buildx", "pip install"):
        assert forbidden not in text, forbidden
    assert "uv sync --locked --no-dev --no-install-project" in text and "sign-release.py" in text
    assert "sha256sum --strict -c SHA256SUMS" in text
    uploads = [s for s in sign["steps"] if str(s.get("uses", "")).startswith("actions/upload")]
    assert [u["with"]["path"] for u in uploads] == ["signature/SHA256SUMS.sig"]
    assert sign["permissions"] == {"contents": "read"}


def test_publishing_waits_for_the_signature_and_nothing_else_publishes():
    all_jobs = jobs()
    assert set(all_jobs["publish"]["needs"]) == {"package", "sign"}
    creating = [n for n, j in all_jobs.items() if "gh release create" in yaml.safe_dump(j)]
    assert creating == ["publish"]
    writers = {n for n, j in all_jobs.items() if (j.get("permissions") or {}).get("contents") == "write"}
    assert writers == {"publish"}
    assert all_jobs["package"]["permissions"] == {"contents": "read"}
    assert "build-release.sh" in yaml.safe_dump(all_jobs["package"])


def test_everything_waits_for_ci_and_the_tag_check():
    all_jobs = jobs()
    assert all_jobs["checks"]["uses"] == "./.github/workflows/ci.yml"
    ci = yaml.safe_load(CI.read_text())
    assert "workflow_call" in ci.get("on", ci.get(True))
    assert set(all_jobs["reuse"]["needs"]) == {"checks", "version"}
    assert set(all_jobs["image"]["needs"]) >= {"checks", "version"}
    version = yaml.safe_dump(all_jobs["version"])
    assert 'scripts/release-version.sh "$GITHUB_REF_NAME"' in version
    assert "sign-release.py --check-pinned" in version


def test_the_agent_image_is_multi_arch_and_reused_when_its_folder_is_unchanged():
    all_jobs = jobs()
    assert "git rev-parse HEAD:images/agent" in yaml.safe_dump(all_jobs["reuse"])
    assert all_jobs["image"]["if"] == "needs.reuse.outputs.image == ''"
    platforms = {entry["platform"] for entry in all_jobs["image"]["strategy"]["matrix"]["include"]}
    assert platforms == {"linux/amd64", "linux/arm64"}
    parsed = yaml.safe_load(WORKFLOW.read_text())
    assert parsed["env"]["IMAGE"] == "ghcr.io/sripadalab-um/um-codex-agent"
    manifest = yaml.safe_dump(all_jobs["manifest"])
    assert "tree-$TREE" in manifest and "imagetools inspect" in manifest
    # Jobs after a skipped build still run, but never after a failure.
    for name in ("manifest", "package", "sign", "publish"):
        assert "!cancelled()" in all_jobs[name]["if"]


def test_a_pre_release_stays_the_latest_until_a_full_release_exists():
    publish = yaml.safe_dump(jobs()["publish"])
    assert "--exclude-pre-releases" in publish and "--prerelease" in publish and "--latest" in publish


# ------------------------------------------------------------------ the tag


@pytest.fixture
def tree(tmp_path) -> Path:
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts" / "release-version.sh", tmp_path / "scripts")
    (tmp_path / "src" / "umcodex").mkdir(parents=True)
    return tmp_path


def tag_check(tree: Path, version: str, tag: str) -> subprocess.CompletedProcess[str]:
    (tree / "src" / "umcodex" / "__init__.py").write_text(f'"""x"""\n\n__version__ = "{version}"\n')
    return subprocess.run(
        ["sh", "scripts/release-version.sh", tag], cwd=tree, capture_output=True, text=True, check=False
    )


@pytest.mark.parametrize(
    ("version", "tag"),
    [
        ("0.1.0a2", "v0.1.0-alpha.2"),
        ("0.1.0a2", "v0.1.0-a2"),
        ("0.1.0a2", "v0.1.0a2"),
        ("0.2.0b1", "v0.2.0-beta.1"),
        ("1.0.0rc3", "v1.0.0-rc.3"),
        ("1.0.0", "v1.0.0"),
    ],
)
def test_the_tag_matches_the_package_version(tree, version, tag):
    done = tag_check(tree, version, tag)
    assert done.returncode == 0, done.stderr
    assert done.stdout == f"{version}\n"


@pytest.mark.parametrize(
    ("version", "tag"),
    [
        ("0.1.0a1", "v0.1.0-alpha.2"),
        ("0.1.0a2", "v0.1.0"),
        ("0.1.0", "v0.1.0-alpha.1"),
        ("0.1.0a2", "0.1.0a2"),
        ("0.1.0a2", "vlatest"),
    ],
)
def test_a_tag_that_doesnt_match_stops_the_release(tree, version, tag):
    done = tag_check(tree, version, tag)
    assert done.returncode == 1 and done.stdout == ""


def test_the_repositorys_own_version_is_a_release_version():
    done = subprocess.run(
        ["sh", "-c", 'v=$(sed -n \'s/^__version__ = "\\(.*\\)"$/\\1/p\' src/umcodex/__init__.py); echo "$v"'],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    from umcodex import __version__

    assert done.stdout.strip() == __version__


# ------------------------------------------------------------------ the files


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    """scripts/build-release.sh, run for real (it builds the wheel with uv)."""
    if shutil.which("uv") is None:
        pytest.skip("uv isn't installed")
    out = tmp_path_factory.mktemp("release") / "assets"
    before = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
    tag = "v" + _tag_for_version()
    subprocess.run(
        ["sh", "scripts/build-release.sh", str(out)],
        cwd=ROOT,
        env={**_env(), "AGENT_IMAGE": AGENT, "RELEASE_TAG": tag},
        check=True,
        capture_output=True,
        text=True,
    )
    after = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
    assert after == before, "build-release.sh changed the repository"
    return out


def _env() -> dict[str, str]:
    import os

    return {k: v for k, v in os.environ.items() if not k.startswith(("UV_", "VIRTUAL_ENV"))}


def _tag_for_version() -> str:
    from umcodex import __version__

    return __version__


def test_the_release_has_exactly_its_files(built):
    from umcodex import __version__

    names = sorted(p.name for p in built.iterdir())
    assert names == sorted(
        [
            f"umcodex-{__version__}-py3-none-any.whl",
            "requirements.txt",
            "images.json",
            "install-macos.sh",
            "uninstall-macos.sh",
            "install-windows.ps1",
            "uninstall-windows.ps1",
            "SHA256SUMS",
        ]
    )
    sums = parse_sums((built / "SHA256SUMS").read_text())
    assert set(sums) == set(names) - {"SHA256SUMS"}
    import hashlib

    for name, digest in sums.items():
        assert hashlib.sha256((built / name).read_bytes()).hexdigest() == digest


def test_the_packages_images_and_requirements_pass_the_updaters_checks(built):
    from umcodex import __version__

    wheel = built / f"umcodex-{__version__}-py3-none-any.whl"
    images = check_images((built / "images.json").read_bytes(), wheel)
    gateway = json.loads((ROOT / "src" / "umcodex" / "images.json").read_text())["gateway"]
    assert images == {"agent": AGENT, "gateway": gateway}
    digest = parse_sums((built / "SHA256SUMS").read_text())[wheel.name]
    requirements = (built / "requirements.txt").read_text()
    check_requirements(requirements, wheel.name, digest)
    assert requirements.endswith(f"./{wheel.name} --hash=sha256:{digest}\n")
    for dependency in ("aiohttp==", "cryptography==", "httpx==", "keyring==", "packaging=="):
        assert f"\n{dependency}" in requirements
    for dev_only in ("pytest==", "ruff==", "pyright==", "pyyaml=="):
        assert dev_only not in requirements
    assert "/tmp" not in requirements and "/var/folders" not in requirements


def test_the_installers_name_this_release_and_nothing_else_changes(built):
    from umcodex import __version__

    base = f"https://github.com/SripadaLab-UM/um-codex/releases/download/v{__version__}"
    wheel = f"umcodex-{__version__}-py3-none-any.whl"
    for source, published, stamped in (
        (
            "installer/macos/install.sh",
            "install-macos.sh",
            {'RELEASE_BASE=""': f'RELEASE_BASE="{base}"', 'RELEASE_WHEEL=""': f'RELEASE_WHEEL="{wheel}"'},
        ),
        (
            "installer/windows/install.ps1",
            "install-windows.ps1",
            {
                '$ReleaseBase = ""': f'$ReleaseBase = "{base}"',
                '$ReleaseWheel = ""': f'$ReleaseWheel = "{wheel}"',
            },
        ),
        ("installer/macos/uninstall.sh", "uninstall-macos.sh", {}),
        ("installer/windows/uninstall.ps1", "uninstall-windows.ps1", {}),
    ):
        original = (ROOT / source).read_text().splitlines()
        expected = [stamped.get(line, line) for line in original]
        assert (built / published).read_text().splitlines() == expected, published
        assert (built / published).read_bytes().isascii() or published.endswith(".sh")


def test_build_release_refuses_an_image_not_pinned_by_digest(tmp_path):
    for image in ("ghcr.io/sripadalab-um/um-codex-agent:latest", "ghcr.io/someone/agent@sha256:" + "a" * 64):
        done = subprocess.run(
            ["sh", "scripts/build-release.sh", str(tmp_path / "out")],
            cwd=ROOT,
            env={**_env(), "AGENT_IMAGE": image, "RELEASE_TAG": "v" + _tag_for_version()},
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == 1 and not (tmp_path / "out").exists(), done.stderr


def test_a_signed_build_installs_through_um_codex_update(built, tmp_path, data_folder):
    """The whole path: the built files, signed with a throwaway key as the sign
    job does, served as GitHub serves a release, checked and installed by an
    older UM-Codex (its uv and the new version's commands stood in for)."""
    import importlib.util
    import os

    from tests.test_update import FakeTools, installed

    private, public = signing.new_key()
    spec = importlib.util.spec_from_file_location("sign_release", ROOT / "scripts" / "sign-release.py")
    assert spec and spec.loader
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assets = tmp_path / "assets"
    shutil.copytree(built, assets)
    from umcodex import __version__, release_keys

    original = release_keys.RELEASE_KEYS
    release_keys.RELEASE_KEYS = (public,)  # type: ignore[misc]
    os.environ["RELEASE_SIGNING_KEY"] = private
    try:
        assert script.main([str(assets / "SHA256SUMS")]) == 0
    finally:
        release_keys.RELEASE_KEYS = original  # type: ignore[misc]
        del os.environ["RELEASE_SIGNING_KEY"]

    github = FakeGitHub()
    try:
        files = {p.name: p.read_bytes() for p in assets.iterdir()}
        github.releases = [FakeRelease("v" + __version__, files)]
        root = tmp_path / "app"
        installed(root, "0.0.1a1")  # a pre-release, so pre-releases are offered
        (root / "current").write_text("0.0.1a1\n")
        tools, said = FakeTools(), []
        up = Updater(
            layout=Layout(root, windows=False, prefix=root / "versions" / "0.0.1a1"),
            source=ReleaseSource(api=github.api),
            keys=[public],
            current="0.0.1a1",
            run=tools,
            uv="uv",
            platform="darwin",
            data=data_folder,
            say=said.append,
        )
        assert up.update() == 0, said
        assert (root / "current").read_text() == f"{__version__}\n"
        assert (root / "previous").read_text() == "0.0.1a1\n"
    finally:
        github.close()
