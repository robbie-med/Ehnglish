"""Metric registry and scales (plan §5.5, §6.1).

Every metric has: a domain, a direction, a bilingual one-line definition, and an extractor that
turns one session's stored results into a value plus the per-item samples behind it (for a
bootstrapped 95% CI). Scales: raw → % of the native anchor on the same form → 0–100 domain scale.
Trends compare sessions of the same form; a change inside the CI overlap is "no detectable change".
CEFR / TOEFL / IELTS are heuristics over the metrics, clearly labelled as estimates (ESTIMATE_RULES),
recalibrated once a real score exists (M6).
"""

from __future__ import annotations

import random
import statistics
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

Samples = list[float]


@dataclass
class MetricDef:
    id: str
    domain: str  # speaking | listening | reading | writing | vocabulary | self | quality
    direction: str  # higher | lower (which way is better) | none (covariate)
    unit: str
    en: str
    ko: str
    extract: Callable[[dict], tuple[float | None, Samples]]
    forms: tuple[str, ...] = ("core", "rotating", "baseline")  # form kinds where it appears


@dataclass
class MetricValue:
    id: str
    value: float | None
    n: int
    ci95: tuple[float, float] | None
    anchor: float | None = None  # anchor mean on the same form
    pct_of_anchor: float | None = None
    scale: float | None = None  # 0–100 relative to anchor
    samples: Samples = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("samples", None)
        return d


# ---------------------------------------------------------------- helpers over a session bundle
# A "bundle" is what dashboard.py builds per session:
# {"takes": [{task_id, item_id, kind, results: {kind: result}, task_type, quality, events}],
#  "session_results": {kind: result}, "setup": {...}}


def _takes(b: dict, task_type: str | None = None, task_id: str | None = None) -> list[dict]:
    out = []
    for t in b["takes"]:
        if task_type and t["task_type"] != task_type:
            continue
        if task_id and t["task_id"] != task_id:
            continue
        out.append(t)
    return out


def _vals(takes: list[dict], kind: str, key: str) -> Samples:
    v = []
    for t in takes:
        r = t["results"].get(kind)
        if r and not r.get("skipped") and r.get(key) is not None:
            v.append(float(r[key]))
    return v


def _mean(v: Samples) -> tuple[float | None, Samples]:
    return (round(statistics.fmean(v), 3) if v else None), v


def _timing(b: dict, task_types: tuple[str, ...], key: str) -> tuple[float | None, Samples]:
    takes = [t for t in b["takes"] if t["task_type"] in task_types and t["kind"] == "audio"]
    return _mean(_vals(takes, "timing", key))


def _free_speech(b: dict) -> list[dict]:
    return [
        t
        for t in b["takes"]
        if t["task_type"] in ("describe_opinion", "quick_answer", "phone_call")
        and t["kind"] == "audio"
        and t["results"].get("transcript")
    ]


def m_speech_rate(b):  # syllables per second over free speech
    return _timing(b, ("describe_opinion", "quick_answer", "phone_call"), "speech_rate_syl_per_s")


def m_articulation_rate(b):
    return _timing(
        b, ("describe_opinion", "quick_answer", "phone_call"), "articulation_rate_syl_per_s"
    )


def m_mlr(b):
    return _timing(b, ("describe_opinion", "quick_answer", "phone_call"), "mean_length_of_run_syl")


def m_pauses_per_min(b):
    return _timing(b, ("describe_opinion", "quick_answer", "phone_call"), "pauses_per_min")


def m_mean_pause(b):
    return _timing(b, ("describe_opinion", "quick_answer", "phone_call"), "mean_pause_s")


def m_fillers_per_100(b):
    v = []
    for t in _free_speech(b):
        lx = t["results"].get("lexical")
        if lx and lx.get("tokens"):
            v.append(100 * lx.get("fillers", 0) / (lx["tokens"] + lx.get("fillers", 0)))
    return _mean(v)


def m_latency(b):
    takes = _takes(b, "quick_answer") + _takes(b, "sentence_repeat") + _takes(b, "phone_call")
    return _mean(_vals(takes, "latency", "latency_ms"))


def m_ei_pct(b):
    return _mean(_vals(_takes(b, "sentence_repeat"), "ei", "pct_syllables"))


def m_ei_longest(b):
    best = 0
    for t in _takes(b, "sentence_repeat"):
        e = t["results"].get("ei")
        if e and e.get("exact"):
            best = max(best, int(e.get("target_syllables", 0)))
    return (float(best) if _takes(b, "sentence_repeat") else None), []


def m_pron_accuracy(b):
    v = []
    for t in _takes(b, "read_aloud"):
        p = t["results"].get("pron")
        if p and not p.get("skipped"):
            v.extend(
                float(w["accuracy"]) for w in p.get("words", []) if w.get("accuracy") is not None
            )
    return _mean(v)


def m_pron_prosody(b):
    return _mean(_vals(_takes(b, "read_aloud"), "pron", "prosody"))


def m_phone_accuracy(b):
    return _mean(_vals(_takes(b, "read_aloud"), "phonemes", "phone_accuracy"))


def m_contrast_errors(b):
    v = []
    for t in _takes(b, "read_aloud"):
        ph = t["results"].get("phonemes")
        if ph and not ph.get("skipped"):
            n = ph.get("n_expected") or 0
            if n:
                v.append(100 * sum(ph.get("contrast_errors", {}).values()) / n)
    return _mean(v)


def m_mtld(b):
    return _mean(_vals(_free_speech(b), "lexical", "mtld"))


def m_beyond_2k(b):
    v = []
    for t in _free_speech(b):
        lx = t["results"].get("lexical")
        if lx and lx.get("tokens"):
            v.append(100 * (1 - lx["band_shares"].get("2k", 1.0)))
    return _mean(v)


def m_subordination(b):
    return _mean(_vals(_free_speech(b), "syntax", "subordination_ratio"))


def m_clause_len(b):
    return _mean(_vals(_free_speech(b), "syntax", "mean_clause_len"))


def m_errors_per_100(b):
    return _mean(_vals(_free_speech(b), "errors", "per_100_words"))


def m_error_free_clauses(b):
    v = [100 * x for x in _vals(_free_speech(b), "errors", "error_free_clause_share")]
    return _mean(v)


def m_phone_goals(b):
    sr = b["session_results"].get("phone_call")
    if sr and sr.get("total"):
        return 100.0 * sr["done"] / sr["total"], [
            100.0 if g["done"] else 0.0 for g in sr.get("goals", [])
        ]
    return None, []


def m_phone_phrases(b):
    used = total = 0
    for t in _takes(b, "phone_call"):
        p = t["results"].get("phrases")
        if p:
            used += p.get("used", 0)
            total += p.get("total", 0)
    return (100.0 * used / total if total else None), []


def m_transcript_agreement(b):
    v = []
    for t in b["takes"]:
        tr = t["results"].get("transcript")
        if tr and tr.get("n_engines", 0) >= 2:
            v.append(100 * float(tr.get("agreement", 0)))
    return _mean(v)


def _dict(b, cond):
    sr = b["session_results"].get("dictation")
    if not sr:
        return None, []
    samples = [
        100 * float(t["results"]["wer"]["wer"])
        for t in _takes(b, "dictation")
        if t["results"].get("wer", {}).get("condition") == cond
    ]
    m = sr["mean_wer"].get(cond)
    return (100 * m if m is not None else None), samples


def m_wer_clear(b):
    return _dict(b, "clear")


def m_wer_fast(b):
    return _dict(b, "fast")


def m_wer_phone(b):
    return _dict(b, "phone")


def m_wer_noise(b):
    return _dict(b, "noise")


def m_phone_penalty(b):
    sr = b["session_results"].get("dictation") or {}
    p = sr.get("phone_penalty")
    return (100 * p if p is not None else None), []


def m_noise_penalty(b):
    sr = b["session_results"].get("dictation") or {}
    p = sr.get("noise_penalty")
    return (100 * p if p is not None else None), []


def _comp(b, genre):
    comp = b["session_results"].get("comprehension") or {}
    for tid, c in comp.items():
        if c.get("genre") == genre:
            samples = [
                100.0 if t["results"]["mc"].get("correct") else 0.0
                for t in _takes(b, task_id=tid)
                if t["results"].get("mc")
            ]
            return c.get("pct"), samples
    return None, []


def m_comp_conversation(b):
    return _comp(b, "conversation")


def m_comp_lecture(b):
    return _comp(b, "lecture")


def m_comp_sermon(b):
    return _comp(b, "sermon")


def m_axb(b):
    sr = b["session_results"].get("axb")
    if not sr:
        return None, []
    return sr.get("pct"), [
        100.0 if t["results"]["axb"].get("correct") else 0.0
        for t in _takes(b, "axb")
        if t["results"].get("axb")
    ]


def m_retell_units(b):
    r = b["session_results"].get("retell") or {}
    v = [float(x["units"]) for x in r.values() if not x.get("skipped")]
    return _mean(v)


def m_reading_wpm(b):
    r = b["session_results"].get("reading") or {}
    v = [float(x["wpm"]) for x in r.values() if x.get("wpm")]
    return _mean(v)


def m_reading_comp(b):
    return (
        _comp(b, "patient_information")
        if _comp(b, "patient_information")[0] is not None
        else _comp(b, "academic")
    )


def m_effective_wpm(b):
    r = b["session_results"].get("reading") or {}
    v = [float(x["effective_wpm"]) for x in r.values() if x.get("effective_wpm")]
    return _mean(v)


def m_ctest(b):
    sr = b["session_results"].get("c_test")
    if not sr:
        return None, []
    samples = [
        100.0 if bl["correct"] else 0.0 for tx in sr.get("texts", []) for bl in tx.get("blanks", [])
    ]
    return sr.get("pct"), samples


def m_email_goals(b):
    sr = b["session_results"].get("email")
    if sr and sr.get("total"):
        return 100.0 * sr["done"] / sr["total"], [
            100.0 if g["done"] else 0.0 for g in sr.get("goals", [])
        ]
    return None, []


def _email_takes(b):
    return [t for t in _takes(b, "typed_response") if t["results"].get("checklist")]


def m_email_errors(b):
    return _mean(_vals(_email_takes(b), "errors", "per_100_words"))


def m_email_mtld(b):
    return _mean(_vals(_email_takes(b), "lexical", "mtld"))


def m_email_subordination(b):
    return _mean(_vals(_email_takes(b), "syntax", "subordination_ratio"))


def m_typing_cpm(b):
    ty = b["session_results"].get("typing") or {}
    v = [float(x["chars_per_min"]) for x in ty.values() if x.get("chars_per_min")]
    if not v:
        v = _vals(_takes(b, "typed_response"), "typing", "chars_per_min")
    return _mean(v)


def m_vocab_size(b):
    sr = b["session_results"].get("vocabulary")
    if not sr or sr.get("size_estimate") is None:
        return None, []
    samples = [
        100.0 if t["results"]["mc"].get("correct") else 0.0
        for t in _takes(b, "multiple_choice")
        if t["results"].get("mc", {}).get("band")
    ]
    return float(sr["size_estimate"]), samples


def m_vocab_medical(b):
    sr = b["session_results"].get("vocabulary") or {}
    return sr.get("medical_pct"), []


def m_lextale(b):
    sr = b["session_results"].get("lextale")
    if not sr:
        return None, []
    samples = [
        100.0 if t["results"]["lexical_decision"].get("correct") else 0.0
        for t in _takes(b, "lexical_decision")
        if t["results"].get("lexical_decision")
        and not t["results"]["lexical_decision"].get("practice")
    ]
    return sr.get("score"), samples


def m_expression_gap(b):
    sr = b["session_results"].get("expression_gap")
    if not sr or sr.get("skipped"):
        return None, []
    return 100 * float(sr.get("coverage", 0)), [
        100.0 if f else 0.0 for f in sr.get("covered_flags", [])
    ]


def m_rate_ratio(b):
    sr = b["session_results"].get("expression_gap") or {}
    return sr.get("speech_rate_ratio"), []


def _rating(b, name):
    r = (b["session_results"].get("ratings") or {}).get(name)
    return (r.get("mean") if r else None), list(r["items"].values()) if r else []


def m_confidence(b):
    return _rating(b, "C7")


def m_cando(b):
    return _rating(b, "cando")


def m_anxiety(b):
    return _rating(b, "anxiety")


def m_noise_floor(b):
    nf = (b["setup"].get("noise_floor") or {}).get("rms_dbfs")
    return nf, []


def m_headphone_leak(b):
    hp = (b["setup"].get("headphones") or {}).get("leak_db")
    return hp, []


def m_clipped_takes(b):
    n = sum(
        1
        for t in b["takes"]
        if t["kind"] == "audio" and (t.get("quality") or {}).get("clip_count", 0) > 0
    )
    return float(n), []


def m_completion(b):
    c = b["session_results"].get("completion") or {}
    return (100 * c["share"] if c.get("share") is not None else None), []


def m_sleep(b):
    return b["setup"].get("sleep_h"), []


def m_stress(b):
    return b["setup"].get("stress"), []


def m_mood(b):
    return b["setup"].get("mood"), []


M = MetricDef
METRICS: list[MetricDef] = [
    M(
        "speech_rate",
        "speaking",
        "higher",
        "syl/s",
        "Syllables per second over free speech, including pauses",
        "휴지를 포함한 자유 발화의 초당 음절 수",
        m_speech_rate,
    ),
    M(
        "articulation_rate",
        "speaking",
        "higher",
        "syl/s",
        "Syllables per second excluding pauses ≥250 ms",
        "250 ms 이상 휴지를 제외한 초당 음절 수",
        m_articulation_rate,
    ),
    M(
        "mean_length_of_run",
        "speaking",
        "higher",
        "syl",
        "Mean number of syllables between pauses",
        "휴지 사이의 평균 음절 수",
        m_mlr,
    ),
    M(
        "pauses_per_min",
        "speaking",
        "lower",
        "/min",
        "Pauses ≥250 ms per minute of speech",
        "발화 1분당 250 ms 이상 휴지 수",
        m_pauses_per_min,
    ),
    M(
        "mean_pause_s",
        "speaking",
        "lower",
        "s",
        "Mean length of pauses ≥250 ms",
        "250 ms 이상 휴지의 평균 길이",
        m_mean_pause,
    ),
    M(
        "fillers_per_100",
        "speaking",
        "lower",
        "/100 w",
        "Filled pauses (um, uh) per 100 words",
        "100단어당 간투사(um, uh) 수",
        m_fillers_per_100,
    ),
    M(
        "response_latency_ms",
        "speaking",
        "lower",
        "ms",
        "Time from the end of the prompt to the first voiced sound",
        "질문 끝에서 첫 발성까지의 시간",
        m_latency,
    ),
    M(
        "ei_pct_syllables",
        "speaking",
        "higher",
        "%",
        "Sentence repetition: share of target syllables reproduced",
        "문장 따라 말하기: 재현된 목표 음절의 비율",
        m_ei_pct,
    ),
    M(
        "ei_longest",
        "speaking",
        "higher",
        "syl",
        "Longest sentence (in syllables) repeated exactly",
        "정확히 따라 말한 가장 긴 문장(음절 수)",
        m_ei_longest,
    ),
    M(
        "pron_accuracy",
        "speaking",
        "higher",
        "/100",
        "Azure pronunciation accuracy per word in the read-aloud",
        "소리 내어 읽기의 단어별 Azure 발음 정확도",
        m_pron_accuracy,
    ),
    M(
        "pron_prosody",
        "speaking",
        "higher",
        "/100",
        "Azure prosody score (stress, intonation, rhythm)",
        "Azure 운율 점수(강세, 억양, 리듬)",
        m_pron_prosody,
    ),
    M(
        "phone_accuracy",
        "speaking",
        "higher",
        "share",
        "Phonemes recognised as expected in the read-aloud",
        "소리 내어 읽기에서 기대대로 인식된 음소의 비율",
        m_phone_accuracy,
    ),
    M(
        "contrast_errors_per_100",
        "speaking",
        "lower",
        "/100 ph",
        "Korean-L1 contrast substitutions (r/l, f/p, …) per 100 expected phonemes",
        "기대 음소 100개당 한국어 화자 특유의 대조 오류(r/l, f/p 등)",
        m_contrast_errors,
    ),
    M(
        "mtld",
        "speaking",
        "higher",
        "",
        "Lexical diversity (MTLD) of free speech",
        "자유 발화의 어휘 다양성(MTLD)",
        m_mtld,
    ),
    M(
        "beyond_2k_pct",
        "speaking",
        "higher",
        "%",
        "Share of words beyond the 2,000 most frequent",
        "최빈 2,000단어 밖 어휘의 비율",
        m_beyond_2k,
    ),
    M(
        "subordination_ratio",
        "speaking",
        "higher",
        "",
        "Subordinate clauses per clause",
        "절당 종속절 수",
        m_subordination,
    ),
    M(
        "mean_clause_len",
        "speaking",
        "higher",
        "w",
        "Words per clause",
        "절당 단어 수",
        m_clause_len,
    ),
    M(
        "errors_per_100",
        "speaking",
        "lower",
        "/100 w",
        "Grammatical edits per 100 words (ERRANT on the minimal correction)",
        "100단어당 문법 수정 수(최소 교정에 ERRANT 적용)",
        m_errors_per_100,
    ),
    M(
        "error_free_clauses_pct",
        "speaking",
        "higher",
        "%",
        "Share of clauses needing no correction",
        "교정이 필요 없는 절의 비율",
        m_error_free_clauses,
    ),
    M(
        "phone_goal_completion",
        "speaking",
        "higher",
        "%",
        "Scripted phone call: goals accomplished",
        "대본 전화 통화: 달성한 목표의 비율",
        m_phone_goals,
    ),
    M(
        "phone_phrases_pct",
        "speaking",
        "higher",
        "%",
        "Scripted phone call: target fixed phrases used",
        "대본 전화 통화: 사용한 목표 고정 표현의 비율",
        m_phone_phrases,
    ),
    M(
        "wer_clear",
        "listening",
        "lower",
        "%",
        "Dictation word error rate, clear audio",
        "받아쓰기 단어 오류율, 깨끗한 음성",
        m_wer_clear,
    ),
    M(
        "wer_fast",
        "listening",
        "lower",
        "%",
        "Dictation word error rate, fast speech",
        "받아쓰기 단어 오류율, 빠른 음성",
        m_wer_fast,
    ),
    M(
        "wer_phone",
        "listening",
        "lower",
        "%",
        "Dictation word error rate, phone line",
        "받아쓰기 단어 오류율, 전화 음질",
        m_wer_phone,
    ),
    M(
        "wer_noise",
        "listening",
        "lower",
        "%",
        "Dictation word error rate, background noise",
        "받아쓰기 단어 오류율, 배경 소음",
        m_wer_noise,
    ),
    M(
        "phone_penalty",
        "listening",
        "lower",
        "pp",
        "Phone WER minus clear WER",
        "전화 오류율에서 깨끗한 음성 오류율을 뺀 값",
        m_phone_penalty,
    ),
    M(
        "noise_penalty",
        "listening",
        "lower",
        "pp",
        "Noise WER minus clear WER",
        "소음 오류율에서 깨끗한 음성 오류율을 뺀 값",
        m_noise_penalty,
    ),
    M(
        "comp_conversation",
        "listening",
        "higher",
        "%",
        "Comprehension questions correct, colleague conversation",
        "동료 대화 이해 문제 정답률",
        m_comp_conversation,
        ("rotating",),
    ),
    M(
        "comp_lecture",
        "listening",
        "higher",
        "%",
        "Comprehension questions correct, mini-lecture",
        "짧은 강의 이해 문제 정답률",
        m_comp_lecture,
        ("rotating",),
    ),
    M(
        "comp_sermon",
        "listening",
        "higher",
        "%",
        "Comprehension questions correct, sermon clip",
        "설교 발췌 이해 문제 정답률",
        m_comp_sermon,
        ("rotating",),
    ),
    M(
        "axb_pct",
        "listening",
        "higher",
        "%",
        "AXB sound discrimination correct",
        "AXB 소리 구별 정답률",
        m_axb,
        ("rotating",),
    ),
    M(
        "retell_units",
        "listening",
        "higher",
        "units",
        "Idea units recalled in the spoken retell",
        "말로 다시 전달한 내용 단위 수",
        m_retell_units,
        ("rotating",),
    ),
    M(
        "transcript_agreement",
        "quality",
        "higher",
        "%",
        "Share of words on which all transcription engines agreed",
        "모든 전사 엔진이 일치한 단어의 비율",
        m_transcript_agreement,
    ),
    M(
        "reading_wpm",
        "reading",
        "higher",
        "wpm",
        "Reading speed, words per minute",
        "읽기 속도, 분당 단어 수",
        m_reading_wpm,
        ("rotating",),
    ),
    M(
        "reading_comp",
        "reading",
        "higher",
        "%",
        "Comprehension questions correct after the timed passage",
        "시간 측정 읽기 후 이해 문제 정답률",
        m_reading_comp,
        ("rotating",),
    ),
    M(
        "effective_wpm",
        "reading",
        "higher",
        "wpm",
        "Reading speed × comprehension",
        "읽기 속도 × 이해도",
        m_effective_wpm,
        ("rotating",),
    ),
    M(
        "ctest_pct",
        "reading",
        "higher",
        "%",
        "C-test blanks completed correctly",
        "C-test 빈칸 정답률",
        m_ctest,
        ("rotating",),
    ),
    M(
        "email_goal_completion",
        "writing",
        "higher",
        "%",
        "Functional email: task points covered",
        "기능적 이메일: 다룬 과제 요점의 비율",
        m_email_goals,
        ("rotating",),
    ),
    M(
        "email_errors_per_100",
        "writing",
        "lower",
        "/100 w",
        "Grammatical edits per 100 words in the email",
        "이메일 100단어당 문법 수정 수",
        m_email_errors,
        ("rotating",),
    ),
    M(
        "email_mtld",
        "writing",
        "higher",
        "",
        "Lexical diversity (MTLD) of the email",
        "이메일의 어휘 다양성(MTLD)",
        m_email_mtld,
        ("rotating",),
    ),
    M(
        "email_subordination",
        "writing",
        "higher",
        "",
        "Subordinate clauses per clause in the email",
        "이메일의 절당 종속절 수",
        m_email_subordination,
        ("rotating",),
    ),
    M(
        "typing_cpm",
        "writing",
        "higher",
        "cpm",
        "Typing speed, characters per minute",
        "타이핑 속도, 분당 글자 수",
        m_typing_cpm,
    ),
    M(
        "vocab_size",
        "vocabulary",
        "higher",
        "families",
        "Estimated vocabulary size (word families) from the band test",
        "빈도대 검사로 추정한 어휘량(단어 가족 수)",
        m_vocab_size,
        ("rotating",),
    ),
    M(
        "vocab_medical_pct",
        "vocabulary",
        "higher",
        "%",
        "Patient-side medical and service items correct",
        "환자 측 의료·서비스 어휘 정답률",
        m_vocab_medical,
        ("rotating",),
    ),
    M(
        "lextale",
        "vocabulary",
        "higher",
        "/100",
        "LexTALE score (baseline only)",
        "LexTALE 점수(기준선에서만)",
        m_lextale,
        ("baseline",),
    ),
    M(
        "expression_gap_pct",
        "speaking",
        "higher",
        "%",
        "Share of Korean idea units also conveyed in English",
        "한국어로 말한 내용 단위 중 영어로도 전달한 비율",
        m_expression_gap,
        ("baseline",),
    ),
    M(
        "speech_rate_ratio",
        "speaking",
        "higher",
        "",
        "English speech rate ÷ Korean speech rate",
        "영어 발화 속도 ÷ 한국어 발화 속도",
        m_rate_ratio,
        ("baseline",),
    ),
    M(
        "confidence",
        "self",
        "none",
        "/10",
        "Self-rated confidence (mean over situations)",
        "자가 평가 자신감(상황 평균)",
        m_confidence,
    ),
    M(
        "cando",
        "self",
        "none",
        "/10",
        "Can-do statements (mean)",
        "할 수 있다 문항(평균)",
        m_cando,
        ("baseline",),
    ),
    M(
        "anxiety",
        "self",
        "none",
        "/10",
        "Speaking anxiety (mean, reverse items flipped)",
        "말하기 불안(평균, 역문항 반전)",
        m_anxiety,
    ),
    M(
        "noise_floor_dbfs",
        "quality",
        "none",
        "dBFS",
        "Room noise floor measured at setup",
        "준비 단계에서 측정한 실내 소음",
        m_noise_floor,
    ),
    M(
        "headphone_leak_db",
        "quality",
        "none",
        "dB",
        "Test tone leaking from headphones into the mic",
        "헤드폰에서 마이크로 새는 신호음",
        m_headphone_leak,
    ),
    M(
        "clipped_takes",
        "quality",
        "none",
        "takes",
        "Recordings with clipping",
        "클리핑이 있는 녹음 수",
        m_clipped_takes,
    ),
    M(
        "completion_pct",
        "quality",
        "none",
        "%",
        "Items completed",
        "완료한 문항 비율",
        m_completion,
    ),
    M("sleep_h", "self", "none", "h", "Sleep the night before", "전날 밤 수면 시간", m_sleep),
    M("stress", "self", "none", "/10", "Stress at the start", "시작 시 스트레스", m_stress),
    M("mood", "self", "none", "/10", "Mood at the start", "시작 시 기분", m_mood),
]
BY_ID = {m.id: m for m in METRICS}


# ---------------------------------------------------------------- CI, anchors, scales, trends
def bootstrap_ci(samples: Samples, *, n: int = 1000, seed: int = 7) -> tuple[float, float] | None:
    if len(samples) < 3:
        return None
    rng = random.Random(seed)
    means = []
    k = len(samples)
    for _ in range(n):
        means.append(statistics.fmean(rng.choice(samples) for _ in range(k)))
    means.sort()
    return round(means[int(0.025 * n)], 3), round(means[int(0.975 * n) - 1], 3)


def evaluate(bundle: dict, form_kind: str) -> dict[str, MetricValue]:
    out: dict[str, MetricValue] = {}
    for m in METRICS:
        if form_kind not in m.forms and form_kind != "dummy":
            continue
        try:
            value, samples = m.extract(bundle)
        except Exception:  # noqa: BLE001 - a missing result must never break the dashboard
            value, samples = None, []
        if value is None:
            continue
        out[m.id] = MetricValue(
            m.id, round(float(value), 3), len(samples), bootstrap_ci(samples), samples=samples
        )
    return out


def apply_anchor(values: dict[str, MetricValue], anchor_means: dict[str, float]) -> None:
    """% of anchor and a 0–100 scale. 'higher' metrics: 100 × value/anchor (capped 120).
    'lower' metrics: 100 × anchor/value. Covariates get no scale."""
    for mid, mv in values.items():
        m = BY_ID[mid]
        a = anchor_means.get(mid)
        if a is None or m.direction == "none":
            continue
        mv.anchor = round(a, 3)
        if m.direction == "higher":
            pct = 100 * mv.value / a if a else None
        else:
            pct = 100 * a / mv.value if mv.value else (100.0 if a == 0 else None)
        if pct is None:
            continue
        mv.pct_of_anchor = round(pct, 1)
        mv.scale = round(max(0.0, min(100.0, pct)), 1)


def trend(points: list[dict], noise: float | None = None) -> dict:
    """points: [{session_id, started_at, value, ci95}] in time order. The latest change is
    'detectable' when it exceeds the test–retest noise floor for this metric (plan §7), or, if no
    noise floor is known yet, when the two CIs do not overlap. Without either, it is None."""
    if len(points) < 2:
        return {"points": points, "change": None, "detectable": None, "noise": noise}
    a, b = points[-2], points[-1]
    change = round(b["value"] - a["value"], 3)
    if noise is not None:
        detectable = abs(change) > noise
    elif a.get("ci95") and b.get("ci95"):
        detectable = b["ci95"][0] > a["ci95"][1] or b["ci95"][1] < a["ci95"][0]
    else:
        detectable = None
    return {"points": points, "change": change, "detectable": detectable, "noise": noise}


def retest_noise(sessions: list[dict], *, max_days: float = 10.0) -> dict[str, float]:
    """Test–retest noise floor per metric: |difference| between two sittings of the same form
    taken within `max_days` of each other (plan §7). sessions: [{form_id, started_at (iso),
    metrics: {id: value}}] in time order. The largest pair difference per metric is kept."""
    from datetime import datetime

    out: dict[str, float] = {}
    for i in range(1, len(sessions)):
        a, b = sessions[i - 1], sessions[i]
        if a["form_id"] != b["form_id"]:
            continue
        ta = datetime.fromisoformat(a["started_at"])
        tb = datetime.fromisoformat(b["started_at"])
        if abs((tb - ta).days) > max_days:
            continue
        for mid, va in a["metrics"].items():
            vb = b["metrics"].get(mid)
            if va is None or vb is None:
                continue
            d = round(abs(vb - va), 3)
            out[mid] = max(out.get(mid, 0.0), d)
    return out


# ---------------------------------------------------------------- estimates (labelled heuristics)
CEFR_ORDER = ["A2", "B1", "B2", "C1", "C2"]
# Official CEFR concordances (ETS 2024 TOEFL iBT section mapping; IELTS band descriptors).
TOEFL_SECTION = {"A2": None, "B1": (4, 17), "B2": (18, 23), "C1": (24, 29), "C2": (30, 30)}
TOEFL_SPEAKING = {"A2": None, "B1": (16, 19), "B2": (20, 24), "C1": (25, 27), "C2": (28, 30)}
TOEFL_WRITING = {"A2": None, "B1": (13, 16), "B2": (17, 23), "C1": (24, 27), "C2": (28, 30)}
TOEFL_LISTENING = {"A2": None, "B1": (9, 16), "B2": (17, 21), "C1": (22, 29), "C2": (30, 30)}
IELTS = {"A2": (3.0, 3.5), "B1": (4.0, 5.0), "B2": (5.5, 6.5), "C1": (7.0, 8.0), "C2": (8.5, 9.0)}

# Each rule: metric id → thresholds for B1, B2, C1, C2 (ascending if higher is better).
ESTIMATE_RULES: dict[str, list[tuple[str, list[float]]]] = {
    "speaking": [
        ("ei_pct_syllables", [55, 75, 90, 97]),
        ("errors_per_100", [12, 7, 3.5, 1.5]),  # lower is better: thresholds descend
        ("speech_rate", [2.2, 3.0, 3.6, 4.2]),
        ("response_latency_ms", [1800, 1200, 800, 500]),
        ("pron_accuracy", [60, 75, 85, 92]),
        ("phone_goal_completion", [40, 65, 85, 100]),
    ],
    "listening": [
        ("wer_clear", [30, 15, 6, 2]),
        ("wer_phone", [45, 25, 12, 5]),
        ("comp_conversation", [40, 60, 80, 95]),
        ("comp_lecture", [40, 60, 80, 95]),
        ("axb_pct", [65, 80, 90, 97]),
    ],
    "reading": [
        ("effective_wpm", [60, 100, 150, 200]),
        ("ctest_pct", [40, 60, 80, 92]),
        ("reading_comp", [50, 70, 85, 95]),
    ],
    "writing": [
        ("email_goal_completion", [40, 65, 85, 100]),
        ("email_errors_per_100", [12, 7, 3.5, 1.5]),
        ("email_subordination", [0.15, 0.3, 0.45, 0.6]),
    ],
}


def _level_index(value: float, thresholds: list[float], direction: str) -> int:
    """0 = A2 … 4 = C2."""
    idx = 0
    for i, th in enumerate(thresholds):
        if (direction == "higher" and value >= th) or (direction == "lower" and value <= th):
            idx = i + 1
    return idx


def estimate_skill(skill: str, values: dict[str, MetricValue]) -> dict:
    levels = []
    used = []
    for mid, ths in ESTIMATE_RULES.get(skill, []):
        mv = values.get(mid)
        if mv is None or mv.value is None:
            continue
        li = _level_index(mv.value, ths, BY_ID[mid].direction)
        levels.append(li)
        used.append({"metric": mid, "value": mv.value, "level": CEFR_ORDER[li]})
    if not levels:
        return {
            "skill": skill,
            "cefr": None,
            "toefl": None,
            "ielts": None,
            "based_on": [],
            "label": "estimate",
        }
    li = int(statistics.median_low(levels))
    cefr = CEFR_ORDER[li]
    toefl_table = {
        "speaking": TOEFL_SPEAKING,
        "writing": TOEFL_WRITING,
        "listening": TOEFL_LISTENING,
        "reading": TOEFL_SECTION,
    }[skill]
    return {
        "skill": skill,
        "cefr": cefr,
        "toefl": toefl_table.get(cefr),
        "ielts": IELTS.get(cefr),
        "based_on": used,
        "spread": max(levels) - min(levels),
        "label": "estimate",
    }


# ---------------------------------------------------------------- external calibration (plan §5.5, §7)
def cefr_from_official(test: str, skill: str, score: float) -> str | None:
    """Official concordance: a TOEFL iBT section score or an IELTS band → CEFR."""
    if test == "ielts":
        for lvl in reversed(CEFR_ORDER):
            lo, _hi = IELTS[lvl]
            if score >= lo:
                return lvl
        return "A2"
    table = {
        "speaking": TOEFL_SPEAKING,
        "writing": TOEFL_WRITING,
        "listening": TOEFL_LISTENING,
        "reading": TOEFL_SECTION,
    }[skill]
    for lvl in reversed(CEFR_ORDER):
        rng = table.get(lvl)
        if rng and score >= rng[0]:
            return lvl
    return "A2"


def calibration_offsets(
    external: list[dict], estimates_by_date: list[tuple[str, dict[str, str | None]]]
) -> dict[str, int]:
    """For each official score, compare its CEFR with our estimate from the nearest sitting on or
    before that date; the level difference becomes the offset applied to later estimates.
    external: [{date, test: 'toefl'|'ielts', speaking, listening, reading, writing}];
    estimates_by_date: [(iso date, {skill: cefr})] in time order."""
    offsets: dict[str, int] = {}
    for ex in external:
        date = str(ex.get("date", ""))
        nearest = None
        for d, est in estimates_by_date:
            if d[:10] <= date[:10]:
                nearest = est
        if nearest is None:
            continue
        for skill in ("speaking", "listening", "reading", "writing"):
            score = ex.get(skill)
            ours = nearest.get(skill)
            if score is None or ours is None:
                continue
            official = cefr_from_official(str(ex.get("test", "toefl")), skill, float(score))
            if official:
                offsets[skill] = CEFR_ORDER.index(official) - CEFR_ORDER.index(ours)
    return offsets


def apply_offset(est: dict, offset: int) -> dict:
    if not est.get("cefr") or not offset:
        return est
    i = max(0, min(len(CEFR_ORDER) - 1, CEFR_ORDER.index(est["cefr"]) + offset))
    cefr = CEFR_ORDER[i]
    skill = est["skill"]
    table = {
        "speaking": TOEFL_SPEAKING,
        "writing": TOEFL_WRITING,
        "listening": TOEFL_LISTENING,
        "reading": TOEFL_SECTION,
    }[skill]
    return {
        **est,
        "cefr": cefr,
        "toefl": table.get(cefr),
        "ielts": IELTS.get(cefr),
        "label": "estimate (calibrated)",
        "offset": offset,
    }
