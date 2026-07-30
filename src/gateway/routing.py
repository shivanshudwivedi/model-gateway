"""Configuration-driven model routing and cost calculation."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from gateway.schemas import GenerationRequest, GenerationResult


class Route(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    providers: list[str] = Field(min_length=1)
    input_cost_per_million: Decimal = Decimal("0")
    output_cost_per_million: Decimal = Decimal("0")

    def price(self, result: GenerationResult) -> Decimal:
        million = Decimal(1_000_000)
        return (
            Decimal(result.usage.input_tokens) * self.input_cost_per_million
            + Decimal(result.usage.output_tokens) * self.output_cost_per_million
        ) / million


class RoutesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    routes: dict[str, Route]


class Router:
    def __init__(self, routes: dict[str, Route], default_route: str) -> None:
        if default_route not in routes:
            raise ValueError(f"default route {default_route!r} is not configured")
        self.routes = routes
        self.default_route = default_route

    @classmethod
    def from_yaml(cls, path: Path, default_route: str) -> Router:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        config = RoutesFile.model_validate(raw)
        return cls(config.routes, default_route)

    def resolve(self, request: GenerationRequest) -> Route:
        name = request.route or self.default_route
        try:
            route = self.routes[name]
        except KeyError as exc:
            raise ValueError(f"unknown route: {name}") from exc
        if request.model:
            return route.model_copy(update={"model": request.model})
        return route
