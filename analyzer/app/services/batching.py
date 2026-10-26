import logging

from app.agents.gigachat_provider.base import BaseGigaChatProvider
from app.agents.report_agent import ReportAgent
from app.exceptions import TokenBudgetExceededError

logger = logging.getLogger(__name__)


def balanced_contiguous(
    items: list[str],
    weights: list[int],
    max_tokens: int,
    max_items: int,
) -> list[list[str]]:
    """Делит целые отчёты на сбалансированные последовательные батчи."""

    if not items:
        return []

    minimum_groups = max(
        1,
        (sum(weights) + max_tokens - 1) // max_tokens,
        (len(items) + max_items - 1) // max_items,
    )
    target_weight = sum(weights) / minimum_groups
    target_items = (len(items) + minimum_groups - 1) // minimum_groups

    result: list[list[str]] = []
    current: list[str] = []
    current_weight = 0
    remaining_groups = minimum_groups

    for index, (item, weight) in enumerate(zip(items, weights, strict=True)):
        remaining_items = len(items) - index
        exceeds_hard_limit = (
            current_weight + weight > max_tokens or len(current) >= max_items
        )
        should_balance = (
            remaining_groups > 1
            and remaining_items >= remaining_groups
            and (
                current_weight + weight > target_weight or len(current) >= target_items
            )
        )

        if current and (exceeds_hard_limit or should_balance):
            result.append(current)
            current = []
            current_weight = 0
            remaining_groups = max(1, remaining_groups - 1)

        current.append(item)
        current_weight += weight

    if current:
        result.append(current)
    return result


async def build_recommendation_with_batches(
    provider: BaseGigaChatProvider,
    agent: ReportAgent,
    items: list[str],
    report_type: str,
    max_tokens: int,
    max_items: int,
) -> str:
    if not items:
        raise ValueError("Нельзя построить агрегированный отчёт без источников")

    weights = [await provider.count_tokens([item]) for item in items]
    if any(weight > max_tokens for weight in weights):
        raise TokenBudgetExceededError(
            "Один неделимый отчёт предыдущего уровня превышает лимит токенов"
        )

    batches = balanced_contiguous(items, weights, max_tokens, max_items)
    logger.info(
        "Report batches ready type=%s count=%s",
        report_type,
        len(batches),
    )
    recommendations = [
        await agent.build_recommendation(batch, f"{report_type}_batch")
        for batch in batches
    ]
    if len(recommendations) == 1:
        return recommendations[0]

    return await build_recommendation_with_batches(
        provider=provider,
        agent=agent,
        items=recommendations,
        report_type=f"{report_type}_merge",
        max_tokens=max_tokens,
        max_items=max_items,
    )
