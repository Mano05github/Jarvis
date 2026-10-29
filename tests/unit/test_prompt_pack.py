from jarvis.benchmarking.corpus import summarize_corpus
from jarvis.benchmarking.prompt_pack import build_phase1_corpus


def test_phase1_prompt_pack_is_balanced_and_deterministic() -> None:
    entries = build_phase1_corpus()
    summary = summarize_corpus(entries)

    assert summary == {
        "utterances": 120,
        "by_language": {"en": 40, "ta": 40, "mixed": 40},
        "by_condition": {
            "quiet-near": 48,
            "normal-room": 48,
            "controlled-noise": 24,
        },
        "by_split": {"development": 96, "held-out": 24},
    }
    assert len({entry.utterance_id for entry in entries}) == 120
    assert len({entry.audio_file for entry in entries}) == 120
