import tempfile
from pathlib import Path
from typing import Generator

import pytest
from docker.errors import BuildError, ImageNotFound

from tomodachi_testcontainers.containers import EphemeralDockerImage, get_docker_image


@pytest.fixture()
def dockerfile_hello_world(tmp_path: Path) -> Generator[Path, None, None]:
    with tempfile.NamedTemporaryFile(mode="wt", encoding="utf-8", dir=tmp_path) as dockerfile:
        dockerfile.writelines(
            [
                "FROM alpine:latest\n",
                "RUN echo 'Hello, world!'\n",
            ]
        )
        dockerfile.flush()
        yield Path(dockerfile.name)


@pytest.fixture()
def dockerfile_buildkit(tmp_path: Path) -> Generator[Path, None, None]:
    with tempfile.NamedTemporaryFile(mode="wt", encoding="utf-8", dir=tmp_path) as dockerfile:
        dockerfile.writelines(
            [
                "FROM alpine:latest\n",
                # -- mount is a buildkit feature
                "RUN --mount=type=secret,id=test,target=test echo 'Hello, World!'\n",
            ]
        )
        dockerfile.flush()
        yield Path(dockerfile.name)


@pytest.fixture()
def dockerfile_multi_stage(tmp_path: Path) -> Generator[Path, None, None]:
    with tempfile.NamedTemporaryFile(mode="wt", encoding="utf-8", dir=tmp_path) as dockerfile:
        dockerfile.writelines(
            [
                "FROM alpine:latest as base\n",
                "ENV PATH=''\n",
                "ENV TARGET=base\n",
                "\n",
                "FROM base as development\n",
                "ENV TARGET=development\n",
                "\n",
                "FROM base as release\n",
                "ENV TARGET=release\n",
            ]
        )
        dockerfile.flush()
        yield Path(dockerfile.name)


def test_build_docker_image_and_remove_on_cleanup(
    dockerfile_hello_world: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DOCKER_BUILDKIT", raising=False)

    with EphemeralDockerImage(dockerfile_hello_world) as image:
        assert get_docker_image(image_id=str(image.id))

    with pytest.raises(ImageNotFound):
        get_docker_image(image_id=str(image.id))


def test_build_with_docker_buildkit(dockerfile_buildkit: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKER_BUILDKIT", "1")

    with EphemeralDockerImage(dockerfile_buildkit) as image:
        assert get_docker_image(image_id=str(image.id))


def test_build_error_when_docker_buildkit_envvar_not_set(
    dockerfile_buildkit: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DOCKER_BUILDKIT", raising=False)

    with pytest.raises(BuildError), EphemeralDockerImage(dockerfile_buildkit):
        pass


def test_default_build_target(dockerfile_multi_stage: Path) -> None:
    with EphemeralDockerImage(dockerfile_multi_stage, target=None) as image:
        assert image.attrs
        assert image.attrs.get("Config", {}).get("Env") == ["PATH=", "TARGET=release"]


@pytest.mark.parametrize("target", ["development", "release"])
def test_explicit_build_target(dockerfile_multi_stage: Path, target: str) -> None:
    with EphemeralDockerImage(dockerfile_multi_stage, target=target) as image:
        assert image.attrs
        assert image.attrs.get("Config", {}).get("Env") == ["PATH=", f"TARGET={target}"]
