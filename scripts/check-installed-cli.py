"""Exercise an installed Prism wheel without activating its virtual environment.

Usage: python scripts/check-installed-cli.py --python <venv-python> --template <repo>
All generated projects and Git commits are confined to a temporary directory.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import yaml


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True)
    parser.add_argument("--template", type=Path, required=True)
    args = parser.parse_args()
    # A virtual environment's interpreter is often a symlink to the base
    # interpreter; resolving it would run the base interpreter without the
    # environment's packages.
    executable = os.path.abspath(args.python)
    source = args.template.resolve()
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("VIRTUAL_ENV", None)
    env["PATH"] = os.pathsep.join(
        item for item in env.get("PATH", "").split(os.pathsep)
        if item and not any((Path(item) / name).exists() for name in ("copier", "copier.exe", "copier.cmd"))
        and os.path.realpath(item) != os.path.realpath(os.path.dirname(executable))
    )
    assert shutil.which("copier", path=env["PATH"]) is None

    def run(cwd: Path, command: list[str], expected: int = 0) -> subprocess.CompletedProcess:
        result = subprocess.run(command, cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace", capture_output=True, stdin=subprocess.DEVNULL)
        assert result.returncode == expected, f"{command}\nexit {result.returncode}\n{result.stdout[-3000:]}\n{result.stderr[-3000:]}"
        return result

    def snapshot_project(project: Path) -> dict[str, bytes | str]:
        snapshot: dict[str, bytes | str] = {}
        for path in project.rglob("*"):
            if ".git" in path.relative_to(project).parts:
                continue
            relative = path.relative_to(project).as_posix()
            if path.is_symlink():
                snapshot[relative] = "symlink:" + os.readlink(path)
            elif path.is_file():
                snapshot[relative] = path.read_bytes()
        return snapshot

    cli = [executable, "-m", "prism_cli"]
    # The simulated version advances derive from the installed CLI, so a release
    # bump needs no edit here.
    installed_version = run(source, [executable, "-c", "from prism_cli import __version__; print(__version__)"]).stdout.strip()
    major, minor, _patch = (int(part) for part in installed_version.split("."))

    def advanced(step: int) -> str:
        return f"{major}.{minor + step}.0"

    def pin_minimum(manifest_template: Path, version: str) -> None:
        text = manifest_template.read_text(encoding="utf-8")
        pinned_text, replaced = re.subn(r"^min_prism_cli_version:[^\r\n]*", f'min_prism_cli_version: "{version}"', text, count=1, flags=re.MULTILINE)
        assert replaced == 1, "the fixture template must declare min_prism_cli_version"
        manifest_template.write_text(pinned_text, encoding="utf-8")

    with tempfile.TemporaryDirectory(prefix="prism-installed-cli-") as directory:
        root = Path(directory)
        # Exercise adoption through the installed entry point, outside the
        # source checkout and without Copier metadata or an application tree.
        adopted = root / "existing-workspace"
        adopted.mkdir()
        (adopted / "notes.txt").write_bytes(b"Existing workspace content\r\n")
        (adopted / "AGENTS.md").write_bytes(b"# Existing team guidance\r\n")
        original = snapshot_project(adopted)
        adoption = ["workflow", "install", str(adopted), "--name", "Document review", "--app", "backend"]
        plan = json.loads(run(root, cli + adoption + ["--json"]).stdout)
        assert not plan["conflicts"], plan["conflicts"]
        assert snapshot_project(adopted) == original, "installation preview must be read-only"
        receipt = json.loads(run(root, cli + adoption + ["--apply", "--yes", "--json"]).stdout)
        assert receipt["status"] == "applied", receipt
        for relative, expected in original.items():
            assert (adopted / relative).read_bytes() == expected
        assert not (adopted / "backend").exists()
        assert not (adopted / ".copier-answers.yml").exists()
        assert not (adopted / ".agents").exists()
        assert not (adopted / ".prism/state").exists()
        run(root, cli + ["board", "status", str(adopted)])
        again = json.loads(run(root, cli + adoption + ["--apply", "--yes", "--json"]).stdout)
        assert again["status"] == "unchanged", again
        run(root, [executable, "-c", "from prism_cli.workflow_assets import list_skills,get_skill,asset_digest; import prism_cli.board_reads,prism_cli.board_mcp,prism_cli.board_server; assert len(list_skills()) == 26; assert get_skill('po-intake')['references']; assert len(asset_digest()) == 64"])
        grant = json.loads(run(root, cli + ["board", "grant", "Installed test reader", "--path", str(adopted), "--kind", "agent"]).stdout)
        assert not grant["participant"]["writable"]
        assert len(grant["token"]) >= 32
        run(root, cli + ["board", "revoke", grant["participant"]["participant_id"], "--path", str(adopted)])
        run(adopted, ["git", "init", "-q"])
        run(adopted, ["git", "check-ignore", "-q", ".prism/state/board.sqlite3"])
        untrusted = root / "untrusted"
        run(root, cli + ["new", "--preset", "backend-only", "--project-name", "Trust Smoke", "--dest", str(untrusted), "--template", str(source), "--yes"], expected=3)
        assert not untrusted.exists()
        for destination in ("relative-project", str(root / "absolute-project")):
            run(root, cli + ["new", "--preset", "backend-only", "--project-name", "Installed Smoke", "--dest", destination, "--template", str(source), "--trust-template", "--yes"])
            project = root / destination
            assert (project / "backend/build.gradle.kts").is_file()
            answers = yaml.safe_load((project / ".copier-answers.yml").read_text(encoding="utf-8"))
            assert Path(answers["_src_path"]) == source
            assert answers["project_name"] == "Installed Smoke"
            assert "_commit" not in answers, "local working-tree generation must not invent a commit baseline"
            assert (project / "prism.workspace.yml").is_file()
            manifest = yaml.safe_load((project / "prism.workspace.yml").read_text(encoding="utf-8"))
            assert manifest["generated_by"]["template_version"] == "unversioned"
            assert manifest["generated_by"]["template_commit"] == "unversioned"

        # A generated project has local Prism guidance but needs explicit
        # workflow adoption before connected writes are enabled. Upgrade must
        # preserve application files and the source-generation provenance.
        project = root / "absolute-project"
        generated_before = snapshot_project(project)
        answers_path = project / ".copier-answers.yml"
        answers_before = answers_path.read_bytes()
        manifest_path = project / "prism.workspace.yml"
        manifest_before = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        status_before = json.loads(run(root, cli + ["board", "status", str(project)], expected=3).stdout)
        assert status_before["compatible"] is False
        assert "workflow" in (status_before.get("reason") or "").lower()
        assert not (project / ".prism").exists(), "board status should not create service state"

        upgrade = ["workflow", "upgrade", str(project)]
        preview = json.loads(run(root, cli + upgrade + ["--json"]).stdout)
        assert not preview["conflicts"], preview["conflicts"]
        assert snapshot_project(project) == generated_before, "workflow upgrade preview must be read-only"
        receipt = json.loads(run(root, cli + upgrade + ["--apply", "--yes", "--json"]).stdout)
        assert receipt["status"] == "applied", receipt
        assert answers_path.read_bytes() == answers_before, "workflow upgrade changed Copier answers"
        manifest_after = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        assert manifest_after["generated_by"] == manifest_before["generated_by"]
        assert manifest_after["workflow"]["mode"] == "generated"
        assert len(manifest_after["workflow"]["asset_digest"]) == 64
        generated_after = snapshot_project(project)
        for relative, content in generated_before.items():
            if relative not in {"prism.workspace.yml", ".gitignore"}:
                assert generated_after.get(relative) == content, f"workflow upgrade changed generated file {relative}"
        status_after = json.loads(run(root, cli + ["board", "status", str(project)]).stdout)
        assert status_after["compatible"] is True, status_after
        assert status_after["workflow"]["mode"] == "generated"

        # A tiny real versioned template tests copy -> customize -> update -> recopy.
        template = root / "versioned-template"
        files = template / "template"
        files.mkdir(parents=True)
        shutil.copyfile(source / "copier.yml", template / "copier.yml")
        shutil.copyfile(source / "template/{{ _copier_conf.answers_file }}.jinja", files / "{{ _copier_conf.answers_file }}.jinja")
        shutil.copyfile(source / "template/prism.workspace.yml.jinja", files / "prism.workspace.yml.jinja")
        text = "user line: original\n" + "unchanged\n" * 20 + "template version: one\n"
        (files / "custom.txt").write_text(text, encoding="utf-8")
        for folder in (template, root / "update-project"):
            folder.mkdir(exist_ok=True)
            run(folder, ["git", "init", "-q"])
            run(folder, ["git", "config", "user.name", "Prism regression fixture"])
            run(folder, ["git", "config", "user.email", "fixture@example.invalid"])
        run(template, ["git", "add", "."])
        run(template, ["git", "commit", "-qm", "fixture version one"])
        run(template, ["git", "tag", "v1.0.0"])
        project = root / "update-project"
        run(root, cli + ["new", "--preset", "backend-only", "--project-name", "Update Smoke", "--dest", str(project), "--template", "git+" + template.as_uri(), "--trust-template", "--yes"])
        saved = yaml.safe_load((project / ".copier-answers.yml").read_text(encoding="utf-8"))
        assert saved["_commit"] == "v1.0.0"
        generated_manifest = yaml.safe_load((project / "prism.workspace.yml").read_text(encoding="utf-8"))
        assert generated_manifest["min_prism_cli_version"] == installed_version
        assert generated_manifest["generated_by"]["prism_cli_version"] == installed_version
        (project / "custom.txt").write_text(text.replace("original", "customized"), encoding="utf-8")
        current_manifest_path = project / "prism.workspace.yml"
        current_manifest = yaml.safe_load(current_manifest_path.read_text(encoding="utf-8"))
        current_manifest["team_notes"] = {"owner": "workspace"}
        current_manifest["project"]["description"] = "Workspace-owned description"
        current_manifest_path.write_text(yaml.safe_dump(current_manifest, sort_keys=False), encoding="utf-8")
        run(project, ["git", "add", "."])
        run(project, ["git", "commit", "-qm", "fixture customization"])
        (files / "custom.txt").write_text(text.replace("version: one", "version: two"), encoding="utf-8")
        manifest_template = files / "prism.workspace.yml.jinja"
        pin_minimum(manifest_template, advanced(1))
        run(template, ["git", "add", "."])
        run(template, ["git", "commit", "-qm", "fixture version two"])
        run(template, ["git", "tag", "v2.0.0"])
        run(root, cli + ["update", str(project), "--trust-template", "--yes"])
        updated = (project / "custom.txt").read_text(encoding="utf-8")
        assert "customized" in updated and "version: two" in updated
        updated_manifest = yaml.safe_load(current_manifest_path.read_text(encoding="utf-8"))
        updated_answers = yaml.safe_load((project / ".copier-answers.yml").read_text(encoding="utf-8"))
        assert "<<<<<<<" not in current_manifest_path.read_text(encoding="utf-8")
        assert updated_manifest["min_prism_cli_version"] == advanced(1)
        assert updated_manifest["team_notes"] == {"owner": "workspace"}
        assert updated_manifest["project"]["description"] == "Workspace-owned description"
        assert updated_manifest["generated_by"]["template_commit"] == updated_answers["_commit"]
        status = run(root, cli + ["status", str(project), "--json"])
        assert "invalid-workspace-manifest-yaml" not in status.stdout
        run(project, ["git", "add", "."])
        run(project, ["git", "commit", "-qm", "fixture updated"])

        current_manifest["min_prism_cli_version"] = advanced(2)
        current_manifest_path.write_text(yaml.safe_dump(current_manifest, sort_keys=False), encoding="utf-8")
        run(project, ["git", "add", "."])
        run(project, ["git", "commit", "-qm", "competing manifest edit"])
        (files / "custom.txt").write_text(text.replace("version: one", "version: three"), encoding="utf-8")
        pin_minimum(manifest_template, advanced(3))
        run(template, ["git", "add", "."])
        run(template, ["git", "commit", "-qm", "fixture version three"])
        run(template, ["git", "tag", "v3.0.0"])
        before_conflict = snapshot_project(project)
        conflict = run(root, cli + ["update", str(project), "--trust-template", "--yes"], expected=3)
        assert "Competing edits" in conflict.stderr
        assert "min_prism_cli_version" in conflict.stderr
        assert snapshot_project(project) == before_conflict, "manifest conflicts must be rejected before project mutation"

        run(root, cli + ["update", str(project), "--strategy", "recopy"], expected=3)
        assert (project / "custom.txt").read_text(encoding="utf-8") == updated
        run(root, cli + ["update", str(project), "--strategy", "recopy", "--trust-template", "--yes"])
        assert "user line: original" in (project / "custom.txt").read_text(encoding="utf-8")
        recopied_manifest = yaml.safe_load(current_manifest_path.read_text(encoding="utf-8"))
        assert recopied_manifest["min_prism_cli_version"] == advanced(3)
        assert "team_notes" not in recopied_manifest
        assert not (project / ".copier-answers.prism-recopy.yml").exists()
        # Substitute only the canonical URL with a local Git remote; exercise the
        # installed default ref selection and the real Copier tag checkout.
        pin_cli = [executable, "-c", "import sys; from prism_cli import cli; cli.DEFAULT_TEMPLATE_URL=sys.argv.pop(1); raise SystemExit(cli.main(sys.argv[1:]))", "git+" + template.as_uri()]
        pin_args = ["new", "--preset", "backend-only", "--project-name", "Pinned Smoke", "--yes"]
        missing = run(root, pin_cli + pin_args + ["--dest", str(root / "missing-tag")], expected=3)
        assert f"v{installed_version}" in missing.stderr and "is not published" in missing.stderr, missing.stderr
        run(template, ["git", "tag", f"v{installed_version}", "v1.0.0"])
        pinned = root / "pinned-project"
        run(root, pin_cli + pin_args + ["--dest", str(pinned)])
        assert "template version: one" in (pinned / "custom.txt").read_text(encoding="utf-8")
        assert yaml.safe_load((pinned / ".copier-answers.yml").read_text(encoding="utf-8"))["_commit"] == f"v{installed_version}"
        print("PASS: installed wheel, preserving workflow adoption, generated-workspace upgrade gate/provenance preservation, packaged skills/transport, read-only default grants and revocation, ignored journal, real manifest update/merge/conflicts, unversioned local provenance, custom trust, explicit recopy, matching/missing release tag")


if __name__ == "__main__":
    main()
