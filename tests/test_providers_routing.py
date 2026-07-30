from decimal import Decimal

import pytest

from gateway.providers.deterministic import DeterministicProvider
from gateway.routing import Route, Router
from gateway.schemas import GenerationRequest, GenerationResult, Message, Usage


def request(**metadata: str) -> GenerationRequest:
    return GenerationRequest(
        messages=[Message(role="user", content="hello world")], metadata=metadata
    )


@pytest.mark.asyncio
async def test_deterministic_modes() -> None:
    provider = DeterministicProvider()
    echoed = await provider.generate(request(), "test")
    reversed_result = await provider.generate(request(test_mode="reverse"), "test")
    fixed = await provider.generate(request(test_mode="fixed", fixed_response="answer"), "test")
    assert echoed.text == "hello world"
    assert echoed.usage.total_tokens == 4
    assert reversed_result.text == "dlrow olleh"
    assert fixed.text == "answer"


def test_router_resolves_route_and_model_override() -> None:
    router = Router(
        {"default": Route(model="base", providers=["one"])},
        default_route="default",
    )
    assert router.resolve(request()).model == "base"
    overridden = request().model_copy(update={"model": "custom"})
    assert router.resolve(overridden).model == "custom"
    with pytest.raises(ValueError, match="unknown route"):
        router.resolve(request().model_copy(update={"route": "missing"}))


def test_route_prices_tokens_with_decimal() -> None:
    route = Route(
        model="test",
        providers=["test"],
        input_cost_per_million=Decimal("2"),
        output_cost_per_million=Decimal("8"),
    )
    result = GenerationResult(
        text="x",
        provider="test",
        model="test",
        usage=Usage(input_tokens=1_000_000, output_tokens=500_000),
        latency_ms=1,
    )
    assert route.price(result) == Decimal("6")
