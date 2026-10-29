"""Repeatable speech benchmark primitives."""

from jarvis.benchmarking.corpus import CorpusEntry, load_corpus
from jarvis.benchmarking.metrics import char_error_rate, exact_match, word_error_rate
from jarvis.benchmarking.process import ExecutionLimits, ExecutionResult, run_bounded

__all__ = [
    "CorpusEntry",
    "ExecutionLimits",
    "ExecutionResult",
    "char_error_rate",
    "exact_match",
    "load_corpus",
    "run_bounded",
    "word_error_rate",
]
