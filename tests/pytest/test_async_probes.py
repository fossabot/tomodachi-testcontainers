import pytest

from tomodachi_testcontainers.pytest.async_probes import probe_during_interval, probe_until


@pytest.mark.asyncio()
async def test_probe_until__fails_and_reraises_exception() -> None:
    def _func() -> None:
        raise ValueError("Something went wrong")

    with pytest.raises(ValueError, match="Something went wrong"):
        await probe_until(_func, probe_interval=0.1, stop_after=0.3)


@pytest.mark.asyncio()
async def test_probe_until__pass_with_synchronous_function() -> None:
    def _func() -> bool:
        return True

    result = await probe_until(_func, probe_interval=0.1, stop_after=0.3)

    assert result is True


@pytest.mark.asyncio()
async def test_probe_until__pass_with_asynchronous_function() -> None:
    async def _func() -> bool:
        return True

    result = await probe_until(_func, probe_interval=0.1, stop_after=0.3)

    assert result is True


@pytest.mark.asyncio()
async def test_probe_until__recovers_after_failure() -> None:
    attempts = [False, False, True]

    def _func() -> None:
        assert attempts.pop(0)

    await probe_until(_func, probe_interval=0.1, stop_after=0.3)


@pytest.mark.asyncio()
async def test_probe_until__timeout_reached() -> None:
    attempts = [False, False, False, False, True]

    def _func() -> None:
        assert attempts.pop(0)

    with pytest.raises(AssertionError, match="assert False"):
        await probe_until(_func, probe_interval=0.1, stop_after=0.3)


@pytest.mark.asyncio()
async def test_probe_during_interval__runs_until_timeout_reached_and_passes__with_synchronous_function() -> None:
    attempts = [True, True, True, True]
    attempt = len(attempts)

    def _func() -> bool:
        nonlocal attempt
        assert len(attempts) == attempt
        assert attempts.pop(0)
        attempt -= 1
        return True

    result = await probe_during_interval(_func, probe_interval=0.1, stop_after=0.3)

    assert result is True


@pytest.mark.asyncio()
async def test_probe_during_interval__runs_until_timeout_reached_and_passes__with_asynchronous_function() -> None:
    attempts = [True, True, True, True]
    attempt = len(attempts)

    async def _func() -> bool:
        nonlocal attempt
        assert len(attempts) == attempt
        assert attempts.pop(0)
        attempt -= 1
        return True

    result = await probe_during_interval(_func, probe_interval=0.1, stop_after=0.3)

    assert result is True


@pytest.mark.asyncio()
async def test_probe_during_interval__fails_with_assertion_error() -> None:
    attempts = [True, True, False, True]

    def _func() -> None:
        assert attempts.pop(0)

    with pytest.raises(AssertionError, match="assert False"):
        await probe_during_interval(_func, probe_interval=0.1, stop_after=0.5)


@pytest.mark.asyncio()
async def test_probe_during_interval__fails_with_other_exceptions() -> None:
    attempts = [True, True, False, True]

    def _func() -> None:
        if attempts.pop(0) is False:
            raise ValueError("Something went wrong")

    with pytest.raises(ValueError, match="Something went wrong"):
        await probe_during_interval(_func, probe_interval=0.1, stop_after=0.5)
