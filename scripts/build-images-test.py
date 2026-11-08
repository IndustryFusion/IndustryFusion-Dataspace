#!/usr/bin/env python3
#
# Copyright (c) 2026 IndustryFusion Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
"""Tests scripts/build-images.sh with a stand-in docker, which records each call and fails when asked to.

    build-images-test.py                  Tests scripts/build-images.sh
    build-images-test.py --script <file>  Tests another copy, such as one with a change undone

Each test runs a copy of the script in its own folder, with only the stand-in on PATH, so neither a real
docker nor a scripts/build-images.env in the checkout is used. Needs bash.
"""

import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import traceback

HERE = pathlib.Path(__file__).resolve().parent
IMAGES = ["gateway", "dsp-gateway", "registry", "management", "adapter", "connector"]
DEFAULT = "k3d-iff.localhost:12345/dataspace/{}:latest"

# Writes each call to the log, one line of arguments separated by tabs. Fails the build or push of the image
# FAKE_FAIL names, as "build:<full name>" or "push:<full name>". Uses only bash itself.
STAND_IN = r"""#!/bin/bash
line="$1"
for argument in "${@:2}"; do line="$line"$'\t'"$argument"; done
printf '%s\n' "$line" >>"$FAKE_LOG"
if [[ "$1" == build ]]; then target="$3"; else target="$2"; fi
if [[ -n "${FAKE_FAIL:-}" && "$FAKE_FAIL" == "$1:$target" ]]; then
  echo "stand-in docker: $1 of $target failed" >&2
  exit 7
fi
exit 0
"""


class Run:
    def __init__(self, answer: subprocess.CompletedProcess, calls: list[list[str]], files: set[str]) -> None:
        self.code = answer.returncode
        self.out = answer.stdout
        self.err = answer.stderr
        self.calls = calls
        # What the run left in its folder, to show that nothing in a config file was run.
        self.files = files

    @property
    def built(self) -> list[str]:
        return [call[2] for call in self.calls if call[0] == "build"]

    @property
    def pushed(self) -> list[str]:
        return [call[1] for call in self.calls if call[0] == "push"]

    def __repr__(self) -> str:
        return f"exit {self.code}\nstdout:\n{self.out}\nstderr:\n{self.err}\ncalls: {self.calls}"


class Harness:
    def __init__(self, script: pathlib.Path) -> None:
        self.script = script

    def run(
        self,
        *arguments: str,
        env: dict[str, str] | None = None,
        config: str | None = None,
        fail: str | None = None,
        docker: bool = True,
    ) -> Run:
        """Runs the script in a fresh folder. config, if given, is written as the folder's scripts/build-images.env."""
        folder = pathlib.Path(tempfile.mkdtemp(prefix="build-images-test-"))
        try:
            (folder / "scripts").mkdir()
            copy = folder / "scripts" / "build-images.sh"
            shutil.copy(self.script, copy)
            if config is not None:
                (folder / "scripts" / "build-images.env").write_text(config)
            tools = folder / "bin"
            tools.mkdir()
            if docker:
                stand_in = tools / "docker"
                stand_in.write_text(STAND_IN)
                stand_in.chmod(0o755)
            log = folder / "calls.log"
            given = {"PATH": str(tools), "FAKE_LOG": str(log), "HOME": str(folder)}
            if fail:
                given["FAKE_FAIL"] = fail
            given.update(env or {})
            answer = subprocess.run(
                ["/bin/bash", str(copy), *arguments],
                cwd=folder,
                env=given,
                capture_output=True,
                text=True,
                timeout=60,
            )
            calls = [line.split("\t") for line in log.read_text().splitlines()] if log.exists() else []
            return Run(answer, calls, {path.name for path in folder.iterdir()})
        finally:
            shutil.rmtree(folder)


TESTS = []


def test(function):
    TESTS.append(function)
    return function


def names(template: str, images: list[str] = IMAGES) -> list[str]:
    return [template.format(image) for image in images]


@test
def defaults_build_and_push_all_six(h: Harness) -> None:
    run = h.run()
    assert run.code == 0, run
    assert run.built == names(DEFAULT), run
    assert run.pushed == names(DEFAULT), run
    assert "Pushed 6 images." in run.out, run


@test
def each_image_is_built_from_its_folder(h: Harness) -> None:
    run = h.run("--build-only")
    builds = {call[2]: call[3:] for call in run.calls if call[0] == "build"}
    for image in IMAGES:
        given = builds[DEFAULT.format(image)]
        if image == "management":
            assert given[0] == "-f" and given[1].endswith("/management/api/Dockerfile"), given
            assert given[2].endswith("/management"), given
        else:
            assert len(given) == 1 and given[0].endswith(f"/{image}"), given


@test
def the_targets_are_shown_first(h: Harness) -> None:
    run = h.run()
    lines = run.out.splitlines()
    assert lines[0] == "Images to build and push:", run
    assert [line.strip() for line in lines[1:7]] == names(DEFAULT), run
    assert lines[7].startswith("Building "), run


@test
def settings_from_the_shell(h: Harness) -> None:
    run = h.run(env={"REGISTRY": "reg.test:5000", "REPO": "team/ds", "VERSION": "1.2.3"})
    assert run.code == 0, run
    assert run.pushed == names("reg.test:5000/team/ds/{}:1.2.3"), run


@test
def settings_from_the_file(h: Harness) -> None:
    run = h.run(config="REGISTRY=file.test:1\nREPO=from-file\nVERSION=0.9\n")
    assert run.code == 0, run
    assert run.pushed == names("file.test:1/from-file/{}:0.9"), run


@test
def a_shell_variable_overrides_the_file(h: Harness) -> None:
    run = h.run(env={"VERSION": "2.0.0"}, config="REGISTRY=file.test:1\nVERSION=1.0.0\n")
    assert run.code == 0, run
    assert run.pushed == names("file.test:1/dataspace/{}:2.0.0"), run


@test
def an_empty_shell_variable_overrides_the_file(h: Harness) -> None:
    run = h.run("--list", env={"REGISTRY": ""}, config="REGISTRY=file.test:1\n")
    assert run.code == 0, run
    assert run.out.split() == names("dataspace/{}:latest"), run


@test
def the_file_may_have_comments_blank_lines_quotes_and_crlf(h: Harness) -> None:
    config = "# a comment\r\n\r\n  REGISTRY=\"quoted.test:2\"\r\nREPO='single'  \r\n   # indented comment\nVERSION=3"
    run = h.run("--list", config=config)
    assert run.code == 0, run
    assert run.out.split() == names("quoted.test:2/single/{}:3"), run


@test
def the_file_is_read_not_run(h: Harness) -> None:
    run = h.run("--list", config="echo ran > marker\n")
    assert run.code != 0, run
    assert "build-images.env, line 1" in run.err and "echo ran > marker" in run.err, run
    assert "marker" not in run.files and run.calls == [], run
    expanded = h.run("--list", config="REGISTRY=$(echo ran > marker)\n")
    assert expanded.code == 0, expanded
    assert "marker" not in expanded.files, expanded
    assert expanded.out.splitlines()[0] == "$(echo ran > marker)/dataspace/gateway:latest", expanded


@test
def another_key_in_the_file_is_refused_with_its_line(h: Harness) -> None:
    run = h.run(config="REGISTRY=a.test\n\nIMAGES=adapter\n")
    assert run.code != 0 and "line 3" in run.err and "IMAGES=adapter" in run.err, run
    assert run.calls == [], run


@test
def a_named_config_file(h: Harness) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as named:
        named.write("REGISTRY=named.test\n")
    try:
        run = h.run("--list", "adapter", env={"BUILD_IMAGES_CONFIG": named.name}, config="REGISTRY=default.test\n")
        assert run.code == 0 and run.out.split() == ["named.test/dataspace/adapter:latest"], run
    finally:
        os.unlink(named.name)


@test
def a_named_config_file_that_is_missing(h: Harness) -> None:
    run = h.run(env={"BUILD_IMAGES_CONFIG": "/nonexistent/settings.env"})
    assert run.code != 0 and "/nonexistent/settings.env" in run.err, run
    assert run.calls == [], run


@test
def named_images_only(h: Harness) -> None:
    run = h.run("connector", "adapter", "connector")
    assert run.code == 0, run
    assert run.built == names(DEFAULT, ["connector", "adapter"]), run
    assert run.pushed == names(DEFAULT, ["connector", "adapter"]), run


@test
def build_only_pushes_nothing(h: Harness) -> None:
    run = h.run("--build-only")
    assert run.code == 0, run
    assert run.built == names(DEFAULT) and run.pushed == [], run
    assert run.out.splitlines()[0] == "Images to build, without pushing:", run
    assert "Nothing was pushed." in run.out, run


@test
def listing_builds_nothing_and_needs_no_docker(h: Harness) -> None:
    run = h.run("--list", env={"REGISTRY": "r.test", "VERSION": "5"}, docker=False)
    assert run.code == 0, run
    assert run.out.split() == names("r.test/dataspace/{}:5"), run
    assert run.calls == [], run


@test
def an_unknown_name(h: Harness) -> None:
    run = h.run("adapter", "nonsense")
    assert run.code != 0, run
    assert "Unknown image: nonsense" in run.err and " ".join(IMAGES) in run.err, run
    assert run.calls == [], run


@test
def an_unknown_option(h: Harness) -> None:
    run = h.run("--push-everywhere")
    assert run.code != 0 and "Unknown option: --push-everywhere" in run.err, run
    assert run.calls == [], run


@test
def build_only_and_list_together_are_refused(h: Harness) -> None:
    run = h.run("--list", "--build-only")
    assert run.code != 0 and "--build-only and --list" in run.err, run


@test
def help_is_shown(h: Harness) -> None:
    run = h.run("--help")
    assert run.code == 0 and "Usage:" in run.out and run.calls == [], run


@test
def an_empty_registry_without_pushing_means_no_prefix(h: Harness) -> None:
    run = h.run("--build-only", env={"REGISTRY": ""})
    assert run.code == 0, run
    assert run.built == names("dataspace/{}:latest") and run.pushed == [], run


@test
def an_empty_registry_is_refused_for_pushing(h: Harness) -> None:
    run = h.run(env={"REGISTRY": ""})
    assert run.code != 0 and "REGISTRY is empty" in run.err, run
    assert run.calls == [], run


@test
def an_empty_repository_or_version_is_refused(h: Harness) -> None:
    for key in ("REPO", "VERSION"):
        run = h.run("--build-only", env={key: ""})
        assert run.code != 0 and f"{key} is empty" in run.err, run
        assert run.calls == [], run
    from_file = h.run("--list", config="VERSION=\n")
    assert from_file.code != 0 and "VERSION is empty" in from_file.err, from_file


@test
def a_failed_build_stops_there(h: Harness) -> None:
    failing = DEFAULT.format("registry")
    run = h.run(fail=f"build:{failing}")
    assert run.code != 0, run
    assert run.err.strip().splitlines()[-1] == f"build-images: Failed: build of {failing}", run
    assert run.built == names(DEFAULT, ["gateway", "dsp-gateway", "registry"]), run
    assert run.pushed == [], run


@test
def a_failed_push_stops_there(h: Harness) -> None:
    failing = DEFAULT.format("management")
    run = h.run(fail=f"push:{failing}")
    assert run.code != 0, run
    assert run.err.strip().splitlines()[-1] == f"build-images: Failed: push of {failing}", run
    assert run.pushed == names(DEFAULT, ["gateway", "dsp-gateway", "registry", "management"]), run


@test
def without_docker(h: Harness) -> None:
    run = h.run(docker=False)
    assert run.code != 0 and "docker was not found" in run.err, run
    assert "Building" not in run.out, run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--script", type=pathlib.Path, default=HERE / "build-images.sh")
    harness = Harness(parser.parse_args().script.resolve())
    failed = 0
    for function in TESTS:
        try:
            function(harness)
        except Exception:  # every failure is reported, and the rest still run
            failed += 1
            print(f"FAIL {function.__name__}")
            traceback.print_exc(limit=1, file=sys.stdout)
        else:
            print(f"ok   {function.__name__}")
    print(f"{len(TESTS) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
