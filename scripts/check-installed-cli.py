"""Exercise an installed Prism wheel without activating its virtual environment.

Usage: python scripts/check-installed-cli.py --python <venv-python> --template <repo>
All generated projects and Git commits are confined to a temporary directory.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import yaml


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True)
    parser.add_argument("--template", type=Path, required=True)
    args = parser.parse_args()
    executable = str(Path(args.python).resolve())
    source = args.template.resolve()
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("VIRTUAL_ENV", None)
    env["PATH"] = os.pathsep.join(
        item for item in env.get("PATH", "").split(os.pathsep)
        if item and not any((Path(item) / name).exists() for name in ("copier", "copier.exe", "copier.cmd"))
        and Path(item).resolve() != Path(executable).parent
    )
    assert shutil.which("copier", path=env["PATH"]) is None

    def run(cwd: Path, command: list[str], expected: int = 0) -> subprocess.CompletedProcess:
        result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, stdin=subprocess.DEVNULL)
        assert result.returncode == expected, f"{command}\nexit {result.returncode}\n{result.stdout[-3000:]}\n{result.stderr[-3000:]}"
        return result

    cli = [executable, "-m", "prism_cli"]
    with tempfile.TemporaryDirectory(prefix="prism-installed-cli-") as directory:
        root = Path(directory)
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
            assert (project / "prism.workspace.yml").is_file()

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
        (project / "custom.txt").write_text(text.replace("original", "customized"), encoding="utf-8")
        run(project, ["git", "add", "."])
        run(project, ["git", "commit", "-qm", "fixture customization"])
        (files / "custom.txt").write_text(text.replace("version: one", "version: two"), encoding="utf-8")
        run(template, ["git", "add", "."])
        run(template, ["git", "commit", "-qm", "fixture version two"])
        run(template, ["git", "tag", "v2.0.0"])
        run(root, cli + ["update", str(project), "--trust-template", "--yes"])
        updated = (project / "custom.txt").read_text(encoding="utf-8")
        assert "customized" in updated and "version: two" in updated
        run(project, ["git", "add", "."])
        run(project, ["git", "commit", "-qm", "fixture updated"])
        run(root, cli + ["update", str(project), "--strategy", "recopy"], expected=3)
        assert (project / "custom.txt").read_text(encoding="utf-8") == updated
        run(root, cli + ["update", str(project), "--strategy", "recopy", "--trust-template", "--yes"])
        assert "user line: original" in (project / "custom.txt").read_text(encoding="utf-8")
        assert not (project / ".copier-answers.prism-recopy.yml").exists()
        # Substitute only the canonical URL with a local Git remote; exercise the
        # installed default ref selection and the real Copier tag checkout.
        pin_cli = [executable, "-c", "import sys; from prism_cli import cli; cli.DEFAULT_TEMPLATE_URL=sys.argv.pop(1); raise SystemExit(cli.main(sys.argv[1:]))", "git+" + template.as_uri()]
        pin_args = ["new", "--preset", "backend-only", "--project-name", "Pinned Smoke", "--yes"]
        missing = run(root, pin_cli + pin_args + ["--dest", str(root / "missing-tag")], expected=5)
        assert "v0.2.0" in missing.stdout
        run(template, ["git", "tag", "v0.2.0", "v1.0.0"])
        pinned = root / "pinned-project"
        run(root, pin_cli + pin_args + ["--dest", str(pinned)])
        assert "template version: one" in (pinned / "custom.txt").read_text(encoding="utf-8")
        assert yaml.safe_load((pinned / ".copier-answers.yml").read_text(encoding="utf-8"))["_commit"] == "v0.2.0"
        print("PASS: installed wheel, absent Copier PATH, relative/absolute destinations, custom trust, raw answers, Git update preservation, explicit recopy, matching/missing release tag")


if __name__ == "__main__":
    main()
