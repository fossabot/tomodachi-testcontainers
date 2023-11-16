import docker
import docker.errors
import pytest
import shortuuid

from tomodachi_testcontainers import DockerContainer
from tomodachi_testcontainers.pytest.async_probes import probe_until


class WorkingContainer(DockerContainer):
    def __init__(self) -> None:
        super().__init__(image="alpine:latest")
        self.with_command("sleep infinity")

    def log_message_on_container_start(self) -> str:
        return "Working container started"


class FailingHealthcheckContainer(DockerContainer):
    def __init__(self) -> None:
        super().__init__(image="alpine:latest")
        self.with_command("sleep infinity")

    def log_message_on_container_start(self) -> str:
        return "Container with a broken healthcheck started"

    def start(self) -> "FailingHealthcheckContainer":
        super().start()
        self.exec("sh -c 'echo \"container healthcheck failed\" >> /proc/1/fd/1'")
        raise RuntimeError("Container healthcheck failed")


class TestCleanup:
    def test_container_started(self) -> None:
        container_name = shortuuid.uuid()

        # We need to keep a reference to the container object, otherwise it will be garbage collected
        _ = WorkingContainer().with_name(container_name).start()

        assert docker.from_env().containers.get(container_name)

    def test_container_removed_on_stop(self) -> None:
        container_name = shortuuid.uuid()
        container = WorkingContainer().with_name(container_name).start()

        container.stop()

        with pytest.raises(docker.errors.NotFound):
            docker.from_env().containers.get(container_name)

    def test_container_stop_is_idempotent(self) -> None:
        container = WorkingContainer().start()

        container.stop()
        container.stop()

    @pytest.mark.asyncio()
    async def test_container_removed_on_garbage_collection(self) -> None:
        container_name = shortuuid.uuid()

        WorkingContainer().with_name(container_name).start()

        # Since we don't have a reference (variable) to the container object,
        # it is eventually garbage collected and removed
        def _assert_container_removed() -> None:
            with pytest.raises(docker.errors.NotFound):
                docker.from_env().containers.get(container_name)

        await probe_until(_assert_container_removed)

    def test_container_removed_on_context_manager_exit(self) -> None:
        container_name = shortuuid.uuid()
        with WorkingContainer().with_name(container_name):
            pass

        with pytest.raises(docker.errors.NotFound):
            docker.from_env().containers.get(container_name)

    def test_container_removed_on_failed_startup(self) -> None:
        container_name = shortuuid.uuid()

        with pytest.raises(
            docker.errors.APIError,
            match=r'unable to start container process: exec: "foo": executable file not found in \$PATH',
        ), WorkingContainer().with_name(container_name).with_command("foo"):
            pass

        with pytest.raises(docker.errors.NotFound):
            docker.from_env().containers.get(container_name)

    def test_container_removed_on_failed_healthcheck(self) -> None:
        container_name = shortuuid.uuid()

        with pytest.raises(RuntimeError), FailingHealthcheckContainer().with_name(container_name):
            pass

        with pytest.raises(docker.errors.NotFound):
            docker.from_env().containers.get(container_name)


class TestLogging:
    def test_container_logs_are_forwarded_on_context_manager_exit(self, capsys: pytest.CaptureFixture) -> None:
        with WorkingContainer() as container:
            container.exec("sh -c 'echo \"my log message\" >> /proc/1/fd/1'")

        stderr = str(capsys.readouterr().err)
        assert "--- Logging error ---" not in stderr  # The error message comes from logger standard library
        assert "my log message" in stderr

    def test_container_logs_are_forwarded_on_failed_healthcheck(self, capsys: pytest.CaptureFixture) -> None:
        with pytest.raises(RuntimeError), FailingHealthcheckContainer():
            pass

        stderr = str(capsys.readouterr().err)
        assert "--- Logging error ---" not in stderr
        assert "container healthcheck failed" in stderr

    def test_container_logs_are_not_forwarded_outside_of_context_manager(self, capsys: pytest.CaptureFixture) -> None:
        container = WorkingContainer().start()

        container.exec("sh -c 'echo \"my log message\" >> /proc/1/fd/1'")

        stderr = str(capsys.readouterr().err)
        assert "--- Logging error ---" not in stderr
        assert "my log message" not in stderr

    def test_logs_prefixed_with_container_name(self, capsys: pytest.CaptureFixture) -> None:
        with WorkingContainer().with_name("my-container-name"):
            pass

        stderr = str(capsys.readouterr().err)
        assert "WorkingContainer (my-container-name): Working container started" in stderr
