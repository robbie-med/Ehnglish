import numpy as np
import pytest

from app.pipeline import ei, praat, text, vote
from app.wav import write_wav


def test_normalize() -> None:
    assert text.normalize("I can't go, it's 2 o'clock!") == [
        "i",
        "cannot",
        "go",
        "it",
        "is",
        "two",
        "o'clock",
    ]
    assert text.normalize("Um, the... the nurse", drop_fillers=True) == ["the", "the", "nurse"]
    assert text.normalize("나는 의료 삽화가가 되고 싶다.") == [
        "나는",
        "의료",
        "삽화가가",
        "되고",
        "싶다",
    ]


class TestVote:
    def W(self, s: str, conf: float = 0.9) -> list[vote.Word]:  # noqa: N802
        return [vote.Word(w, conf=conf) for w in s.split()]

    def test_unanimous(self) -> None:
        r = vote.vote(
            {
                "a": self.W("the nurse will call"),
                "b": self.W("the nurse will call"),
                "c": self.W("The nurse will call."),
            }
        )
        assert r.text == "the nurse will call"
        assert r.agreement == 1.0 and r.uncertain_share == 0.0
        assert all(not w.uncertain for w in r.words)

    def test_majority_fixes_one_engine(self) -> None:
        r = vote.vote(
            {
                "a": self.W("the nurse will call"),
                "b": self.W("the nurse well call"),
                "c": self.W("the nurse will call"),
            }
        )
        assert r.text == "the nurse will call"
        assert r.words[2].votes == 2 and not r.words[2].uncertain

    def test_no_majority_is_uncertain(self) -> None:
        r = vote.vote(
            {"a": self.W("the nurse"), "b": self.W("the purse"), "c": self.W("the verse")}
        )
        assert r.words[1].uncertain
        assert r.confident_text == "the"
        assert r.uncertain_share == 0.5

    def test_insertion_by_one_engine_is_dropped(self) -> None:
        r = vote.vote(
            {
                "a": self.W("call the office"),
                "b": self.W("call um the office"),
                "c": self.W("call the office"),
            }
        )
        assert r.text == "call the office"

    def test_insertion_by_majority_is_kept(self) -> None:
        r = vote.vote(
            {
                "a": self.W("call the office"),
                "b": self.W("call um the office"),
                "c": self.W("call um the office"),
            }
        )
        assert r.text == "call um the office"

    def test_low_confidence_marks_uncertain(self) -> None:
        r = vote.vote(
            {
                "a": self.W("hello there", conf=0.2),
                "b": self.W("hello there", conf=0.3),
                "c": self.W("hello there", conf=0.2),
            }
        )
        assert all(w.uncertain for w in r.words)

    def test_timing_from_winners(self) -> None:
        a = [vote.Word("hi", 0.0, 0.3, 0.9), vote.Word("there", 0.35, 0.7, 0.9)]
        b = [vote.Word("hi", 0.02, 0.31, 0.9), vote.Word("there", 0.36, 0.72, 0.9)]
        r = vote.vote({"a": a, "b": b})
        assert r.words[1].start == 0.35 and r.words[1].end == 0.72


class TestEI:
    def test_syllables(self) -> None:
        assert ei.syllables("pharmacy") == 3
        assert ei.syllables("appointment") == 3
        assert ei.syllables("the") == 1
        assert ei.syllables("zzqx") == 1  # fallback never returns 0

    def test_exact(self) -> None:
        s = ei.score_repetition("The pharmacy closes at nine.", "the pharmacy closes at nine")
        assert s.exact and s.pct_syllables == 100.0 and s.target_syllables == 8

    def test_partial_and_missing(self) -> None:
        s = ei.score_repetition("Please bring your insurance card.", "please bring insurance card")
        assert s.words_correct == 4 and not s.exact
        assert s.syllables_correct == s.target_syllables - ei.syllables("your")
        s2 = ei.score_repetition("The nurse will call you back.", "the nurse will call you bag")
        assert [c for _, _, c in s2.alignment][-1] == 0.5  # near miss = half credit

    def test_fillers_ignored_and_longest(self) -> None:
        s = ei.score_repetition("Take one tablet twice a day.", "um take one tablet twice a day")
        assert s.exact
        assert ei.longest_exact([(8, s), (12, ei.score_repetition("a b c", "a"))]) == 8


@pytest.fixture
def speech_like(tmp_path):
    """Four 'syllables' (AM bursts) then a 400 ms pause then three more, at 16 kHz."""
    sr = 16000

    def burst(n: int, gap: float) -> np.ndarray:
        out = []
        for _ in range(n):
            t = np.arange(int(0.18 * sr)) / sr
            env = np.sin(np.pi * t / 0.18) ** 2
            out.append(
                0.4 * env * np.sin(2 * np.pi * 140 * t) * (1 + 0.5 * np.sin(2 * np.pi * 280 * t))
            )
            out.append(np.zeros(int(gap * sr)))
        return np.concatenate(out)

    x = np.concatenate(
        [
            np.zeros(int(0.5 * sr)),
            burst(4, 0.06),
            np.zeros(int(0.4 * sr)),
            burst(3, 0.06),
            np.zeros(int(0.3 * sr)),
        ]
    )
    rng = np.random.default_rng(1)
    x += rng.normal(0, 0.0005, x.shape)
    p = tmp_path / "s.wav"
    write_wav(p, x.astype(np.float32), sr)
    return p


def test_praat_timing(speech_like) -> None:
    r = praat.analyze(speech_like)
    assert 6 <= r.n_syllables <= 8
    assert r.n_pauses == 1
    assert 0.3 <= r.mean_pause_s <= 0.6
    assert 0.45 <= r.onset_s <= 0.6  # latency: first nucleus after 0.5 s of silence
    assert r.articulation_rate_syl_per_s > r.speech_rate_syl_per_s
    assert r.mean_length_of_run_syl is not None and 3 <= r.mean_length_of_run_syl <= 4
    assert r.pitch_median_hz is not None and 120 < r.pitch_median_hz < 160
    d = r.to_dict()
    assert isinstance(d["nuclei"], list) and len(d["pauses"]) == 1
