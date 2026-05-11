"""LLM cost tracking and estimation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostEstimate:
    """Estimated cost of LLM usage."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float


# Default pricing per 1M tokens (USD)
_DEFAULT_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
}


class CostTracker:
    """Track and estimate LLM costs from token usage."""

    def __init__(self, model_pricing: dict[str, dict[str, float]] | None = None):
        self._pricing = model_pricing or _DEFAULT_PRICING

    def estimate(self, model: str, usage: dict[str, int]) -> CostEstimate:
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        total_tokens = prompt_tokens + completion_tokens

        pricing = self._pricing.get(model, self._pricing.get("gpt-4o", {"input": 2.50, "output": 10.00}))
        cost = (prompt_tokens * pricing["input"] + completion_tokens * pricing["output"]) / 1_000_000

        return CostEstimate(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=round(cost, 6),
        )

    def accumulate(self, usages: list[dict[str, int]], model: str = "gpt-4o") -> CostEstimate:
        total_prompt = sum(u.get("prompt_tokens", 0) for u in usages)
        total_completion = sum(u.get("completion_tokens", 0) for u in usages)
        return self.estimate(model, {"prompt_tokens": total_prompt, "completion_tokens": total_completion})
