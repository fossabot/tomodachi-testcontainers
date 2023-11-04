import abc
import os
import subprocess  # nosec: B404
from pathlib import Path
from types import TracebackType
from typing import Any, Dict, Iterator, Optional, Tuple, Type, cast

from docker.models.images import Image as DockerImage
from testcontainers.core.container import DockerContainer as TestcontainersDockerContainer
from testcontainers.core.docker_client import DockerClient
from testcontainers.core.utils import inside_container

from tomodachi_testcontainers.utils import setup_logger


class DockerContainer(abc.ABC, TestcontainersDockerContainer):
    def __init__(self, *args: Any, network: Optional[str] = None, **kwargs: Any) -> None:
        self.logger = setup_logger(self.__class__.__name__)
        self.network = network or os.getenv("TESTCONTAINER_DOCKER_NETWORK") or "bridge"
        super().__init__(*args, **kwargs, network=self.network)

    @abc.abstractmethod
    def log_message_on_container_start(self) -> str:
        pass

    def get_container_host_ip(self) -> str:
        host = self.get_docker_client().host()
        if not host:
            return "localhost"
        if inside_container() and not os.getenv("DOCKER_HOST"):
            gateway_ip = self.get_container_gateway_ip()
            if gateway_ip == host:
                return self.get_container_internal_ip()
            return gateway_ip
        return host

    def get_container_internal_ip(self) -> str:
        container = self.get_docker_client().get_container(self.get_wrapped_container().id)
        return container["NetworkSettings"]["Networks"][self.network]["IPAddress"]

    def get_container_gateway_ip(self) -> str:
        container = self.get_docker_client().get_container(self.get_wrapped_container().id)
        return container["NetworkSettings"]["Networks"][self.network]["Gateway"]

    def start(self) -> "DockerContainer":
        try:
            self._start()
            if message := self.log_message_on_container_start():
                self.logger.info(message)
            return self
        except Exception:
            self._forward_container_logs_to_logger()
            raise

    def stop(self) -> None:
        self._forward_container_logs_to_logger()
        self._stop()

    def restart(self) -> None:
        self.get_wrapped_container().restart()

    def _start(self) -> None:
        self.logger.info(f"Pulling image: {self.image}")
        self._container = self.get_docker_client().run(
            image=self.image,
            command=self._command or "",
            detach=True,
            environment=self.env,
            ports=self.ports,
            name=self._name,
            volumes=self.volumes,
            **self._kwargs,
        )
        self.logger.info(f"Container started: {self._container.short_id}")

    def _stop(self) -> None:
        super().stop(force=True, delete_volume=True)
        self._container = None

    def _forward_container_logs_to_logger(self) -> None:
        if container := self.get_wrapped_container():
            logs = bytes(container.logs(timestamps=True)).decode().split("\n")
            for log in logs:
                self.logger.info(log)


class EphemeralDockerImage:
    """Builds a Docker image from a given Dockerfile and removes it when the context manager exits."""

    image: DockerImage

    def __init__(
        self,
        dockerfile: Optional[Path] = None,
        context: Optional[Path] = None,
        target: Optional[str] = None,
        docker_client_kwargs: Optional[Dict] = None,
    ) -> None:
        self.dockerfile = str(dockerfile) if dockerfile else None
        self.context = str(context) if context else "."
        self.target = target
        self._docker_client = DockerClient(**(docker_client_kwargs or {}))

    def __enter__(self) -> DockerImage:
        self.build_image()
        return self.image

    def __exit__(
        self, exc_type: Optional[Type[BaseException]], exc_val: Optional[BaseException], exc_tb: Optional[TracebackType]
    ) -> None:
        self.remove_image()

    def build_image(self) -> None:
        if os.getenv("DOCKER_BUILDKIT"):
            self.image = self._build_with_docker_buildkit()
        else:
            self.image = self._build_with_docker_client()

    def remove_image(self) -> None:
        self._docker_client.client.images.remove(image=str(self.image.id))

    def _build_with_docker_buildkit(self) -> DockerImage:
        cmd = ["docker", "build", "-q", "--rm=true"]
        if self.dockerfile:
            cmd.extend(["-f", self.dockerfile])
        if self.target:
            cmd.extend(["--target", self.target])
        cmd.append(self.context)

        result = subprocess.run(  # nosec: B603
            cmd,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        image_id = result.stdout.decode("utf-8").strip()
        return cast(DockerImage, self._docker_client.client.images.get(image_id))

    def _build_with_docker_client(self) -> DockerImage:
        image, _ = cast(
            Tuple[DockerImage, Iterator],
            self._docker_client.client.images.build(
                dockerfile=self.dockerfile,
                path=self.context,
                target=self.target,
                forcerm=True,
            ),
        )
        return image
