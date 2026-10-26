class AnalyzerError(Exception):
    """Базовая ожидаемая ошибка Analyzer."""


class EntityNotFoundError(AnalyzerError):
    """Требуемый диалог или отчёт не найден."""


class InvalidAnalysisResultError(AnalyzerError):
    """Анализатор вернул данные, нарушающие доменный контракт."""


class TokenBudgetExceededError(AnalyzerError):
    """Один неделимый источник не помещается в лимит токенов."""
