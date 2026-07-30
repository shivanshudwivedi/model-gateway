import pytest

from gateway.executor import ExecutionError, Executor
from gateway.providers.base import ProviderError
from gateway.routing import Route, Router
from gateway.schemas import GenerationRequest, GenerationResult, Message


class StubProvider:
    def __init__(self, name: str, failures: int = 0, transient: bool = True) -> None:
        self.name = name
        self.failures = failures
        self.transient = transient
        self.calls = 0

    async def generate(self, request: GenerationRequest, model: str) -> GenerationResult:
        self.calls += 1
        if self.calls <= self.failures:
            raise ProviderError("boom", transient=self.transient)
        return GenerationResult(
            text=request.messages[-1].content,
            provider=self.name,
            model=model,
            latency_ms=1,
        )


def payload() -> GenerationRequest:
    return GenerationRequest(messages=[Message(role="user", content="hello")])


@pytest.mark.asyncio
async def test_retries_transient_error() -> None:
    provider = StubProvider("primary", failures=1)
    executor = Executor(
        Router({"route": Route(model="m", providers=["primary"])}, "route"),
        {"primary": provider},
        max_attempts=2,
    )
    result = await executor.execute(payload())
    assert result.provider == "primary"
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_permanent_error_falls_back_without_retry() -> None:
    primary = StubProvider("primary", failures=5, transient=False)
    fallback = StubProvider("fallback")
    executor = Executor(
        Router({"route": Route(model="m", providers=["primary", "fallback"])}, "route"),
        {"primary": primary, "fallback": fallback},
        max_attempts=3,
    )
    result = await executor.execute(payload())
    assert result.provider == "fallback"
    assert primary.calls == 1


@pytest.mark.asyncio
async def test_all_providers_fail() -> None:
    provider = StubProvider("broken", failures=5, transient=False)
    executor = Executor(
        Router({"route": Route(model="m", providers=["missing", "broken"])}, "route"),
        {"broken": provider},
    )
    with pytest.raises(ExecutionError, match="not configured"):
        await executor.execute(payload())
