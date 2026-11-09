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

Each test runs a copy of the script in its own folder, with only the stand-in on PATH and only the variables
the test gives, so neither a real docker nor the caller's settings are used. Needs bash.
"""

import argparse
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
    def __init__(self, answer: subprocess.CompletedProcess, calls: list[list[str]]) -> None:
        self.code = answer.returncode
        self.out = answer.stdout
        self.err = answer.stderr
        self.calls = calls

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
        """Runs the script in a fresh folder. config is written as scripts/build-images.env, to show it isn't read."""
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
            return Run(answer, calls)
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
    run = h.run(env={"LOCAL_REGISTRY": "reg.test:5000", "MAIN_REPO": "team/ds", "MAIN_VERSION": "1.2.3"})
    assert run.code == 0, run
    assert run.pushed == names("reg.test:5000/team/ds/{}:1.2.3"), run


@test
def an_empty_shell_variable_is_used_not_the_default(h: Harness) -> None:
    run = h.run("--list", env={"LOCAL_REGISTRY": ""})
    assert run.code == 0, run
    assert run.out.split() == names("dataspace/{}:latest"), run


@test
def a_config_file_is_not_read(h: Harness) -> None:
    run = h.run("--list", "adapter", config="LOCAL_REGISTRY=file.test:1\nMAIN_VERSION=9\nREGISTRY=old.test\n")
    assert run.code == 0 and run.out.split() == [DEFAULT.format("adapter")], run
    named = h.run("--list", "adapter", env={"BUILD_IMAGES_CONFIG": "/nonexistent/settings.env"})
    assert named.code == 0 and named.out.split() == [DEFAULT.format("adapter")], named


@test
def the_old_names_are_reported_and_not_used(h: Harness) -> None:
    run = h.run("--list", "adapter", env={"REGISTRY": "old.test", "VERSION": "9"})
    assert run.code == 0 and run.out.split() == [DEFAULT.format("adapter")], run
    assert "REGISTRY VERSION set, but not read" in run.err and "LOCAL_REGISTRY, MAIN_REPO and MAIN_VERSION" in run.err
    quiet = h.run("--list", "adapter")
    assert quiet.err == "", quiet


@test
def the_settings_of_env_sh_are_used(h: Harness) -> None:
    run = h.run(
        "--list", "adapter", env={"LOCAL_REGISTRY": "env.test:5000", "MAIN_REPO": "team/ds", "MAIN_VERSION": "2"}
    )
    assert run.code == 0 and run.out.split() == ["env.test:5000/team/ds/adapter:2"], run


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
    run = h.run("--list", env={"LOCAL_REGISTRY": "r.test", "MAIN_VERSION": "5"}, docker=False)
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
    run = h.run("--build-only", env={"LOCAL_REGISTRY": ""})
    assert run.code == 0, run
    assert run.built == names("dataspace/{}:latest") and run.pushed == [], run


@test
def an_empty_registry_is_refused_for_pushing(h: Harness) -> None:
    run = h.run(env={"LOCAL_REGISTRY": ""})
    assert run.code != 0 and "LOCAL_REGISTRY is empty" in run.err, run
    assert run.calls == [], run


@test
def an_empty_repository_or_version_is_refused(h: Harness) -> None:
    for key in ("MAIN_REPO", "MAIN_VERSION"):
        run = h.run("--build-only", env={key: ""})
        assert run.code != 0 and f"{key} is empty" in run.err, run
        assert run.calls == [], run


BAD_REGISTRIES = [
    "reg:5000/",
    "reg:5000 # comment",
    '"unterminated',
    "reg:5000/Team",
    "reg:5000//x",
    "a..b",
    "-reg:5000",
    "reg:port",
    "https://reg:5000",
    "reg:5000/x/",
]
GOOD_REGISTRIES = [
    "reg",
    "reg.example.com",
    "reg.example.com:5000",
    "Reg.Example:5000",
    "10.0.0.1:5000",
    "reg:5000/team/x",
]


@test
def a_registry_that_is_not_one_is_refused_even_for_listing(h: Harness) -> None:
    for value in BAD_REGISTRIES:
        for mode in ("--list", "--build-only"):
            run = h.run(mode, env={"LOCAL_REGISTRY": value})
            assert run.code != 0, (value, run)
            assert f"LOCAL_REGISTRY is not a registry address (set in the shell): '{value}'" in run.err, (value, run)
            assert run.out == "" and run.calls == [], (value, run)


@test
def a_port_outside_the_range_is_refused(h: Harness) -> None:
    for value in ("reg:0", "reg:65536", "reg:123456", "reg:99999/team"):
        run = h.run("--list", env={"LOCAL_REGISTRY": value})
        assert run.code != 0 and "port outside 1 to 65535" in run.err and run.out == "", (value, run)
    edge = h.run("--list", "adapter", env={"LOCAL_REGISTRY": "reg:65535"})
    assert edge.code == 0 and edge.out.split() == ["reg:65535/dataspace/adapter:latest"], edge


@test
def registry_addresses_are_accepted(h: Harness) -> None:
    for value in GOOD_REGISTRIES:
        run = h.run("--list", "adapter", env={"LOCAL_REGISTRY": value})
        assert run.code == 0 and run.out.split() == [f"{value}/dataspace/adapter:latest"], (value, run)


@test
def a_repository_that_is_not_one_is_refused(h: Harness) -> None:
    for value in ("Data/Space", "data//space", "data/", "/data", "a___b", "a-.b", "a.", "data space", "a:b"):
        run = h.run("--list", env={"MAIN_REPO": value})
        assert run.code != 0, (value, run)
        assert f"MAIN_REPO is not a repository path (set in the shell): '{value}'" in run.err and run.out == "", (
            value,
            run,
        )
    for value in ("data/space", "a__b", "a--b", "a.b_c", "team/data-space/x"):
        run = h.run("--list", "adapter", env={"MAIN_REPO": value})
        assert run.code == 0 and run.out.split() == [f"k3d-iff.localhost:12345/{value}/adapter:latest"], (value, run)


@test
def a_version_that_is_not_a_tag_is_refused(h: Harness) -> None:
    for value in ("bad tag", ".1", "-x", "1/2", "v1:2", "a" * 129, "1.2.3 "):
        run = h.run("--list", env={"MAIN_VERSION": value})
        assert run.code != 0, (value, run)
        assert f"MAIN_VERSION is not a tag (set in the shell): '{value}'" in run.err and run.out == "", (value, run)
    for value in ("1.2.3", "v1_2-rc.1", "_x", "a" * 128):
        run = h.run("--list", "adapter", env={"MAIN_VERSION": value})
        assert run.code == 0 and run.out.split() == [f"k3d-iff.localhost:12345/dataspace/adapter:{value}"], run


@test
def a_name_longer_than_docker_allows_is_refused(h: Harness) -> None:
    # k3d-iff.localhost:12345/<repo>/dsp-gateway is 36 characters beside the repository.
    run = h.run("--list", env={"MAIN_REPO": "a" * 220})
    assert run.code != 0 and "Docker allows 255" in run.err and run.out == "", run
    fits = h.run("--list", env={"MAIN_REPO": "a" * 219})
    assert fits.code == 0 and len(fits.out.splitlines()) == 6, fits


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
