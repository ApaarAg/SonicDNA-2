from __future__ import annotations

import json
import os
import re
import time
from typing import Callable, Dict, Iterable, List, Optional, Sequence

import requests


OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_OPENROUTER_MODEL = "openrouter/free"

MIN_QUESTIONS = 1
MAX_QUESTIONS = 5

DIMENSION_ORDER = [
    "emotional_context",
    "movement_danceability",
    "tempo_energy",
    "lyric_vs_instrumental",
    "listening_context",
]

DIMENSION_ALIASES = {
    "danceability": "movement_danceability",
    "movement": "movement_danceability",
    "movement_danceability": "movement_danceability",
    "tempo": "tempo_energy",
    "tempo_preference": "tempo_energy",
    "energy": "tempo_energy",
    "tempo_energy": "tempo_energy",
    "listening_habit": "listening_context",
    "listening_context": "listening_context",
    "lyrics": "lyric_vs_instrumental",
    "lyric_vs_instrumental": "lyric_vs_instrumental",
    "instrumentalness": "lyric_vs_instrumental",
    "emotional_context": "emotional_context",
    "mood": "emotional_context",
}

QUESTION_BANK = {
    "emotional_context": [
        ("What emotion does your go-to music usually carry?", "Joy, melancholy, hype, peace, tension, nostalgia, or something harder to name."),
        ("What feeling are you usually trying to keep alive with music?", "A mood you chase, protect, or return to."),
        ("When a song really lands, what emotion does it unlock first?", "Think body-level reaction, not genre."),
    ],
    "movement_danceability": [
        ("Does your music make you move, or hold you still?", "Think about what your body does when a favorite track comes on."),
        ("How much should your ideal song pull your body into rhythm?", "Stillness, head-nod, full dance, or something between."),
        ("Do you trust a beat first, or the atmosphere around it?", "The part of a song that catches you before lyrics do."),
    ],
    "tempo_energy": [
        ("Do you reach for something fast and electric, or slow and warm?", "The default energy level of your playlist."),
        ("What pace feels most natural when you choose music for yourself?", "Slow burn, mid-tempo, sprint, or a shifting arc."),
        ("Should your music lift your pulse, lower it, or move between both?", "Describe the energy shape you like."),
    ],
    "lyric_vs_instrumental": [
        ("Are you there for the words, or the sound behind them?", "Lyrics that hit you vs music you get completely lost inside."),
        ("When lyrics and texture compete, which one usually wins for you?", "Voice, story, rhythm, melody, or atmosphere."),
        ("Do vocals need to say something, or can they work like another instrument?", "How language matters in your listening."),
    ],
    "listening_context": [
        ("Where does music matter most in your day?", "Commute, workout, late night, background while working, or somewhere else."),
        ("What situation makes you most picky about the music playing?", "A place, time, person, or ritual."),
        ("When do you notice a song is exactly right for the moment?", "Describe the setting around that feeling."),
    ],
}

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "do", "does", "for",
    "from", "how", "in", "is", "it", "its", "most", "music", "of", "or",
    "the", "to", "what", "when", "where", "which", "with", "you", "your",
}


class ProviderError(Exception):
    pass


def _clean_text(value: object, limit: int = 220) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or "")).strip()
    text = re.sub(r"\s+", " ", text)
    return text[:limit].strip()


def _extract_json_object(text: str) -> dict:
    raw = str(text or "").strip()
    if "```" in raw:
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else parts[0]
        raw = re.sub(r"^\s*json\s*", "", raw, flags=re.I)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            raise ProviderError("Provider returned non-JSON content")
        return json.loads(match.group(0))


def normalize_dimension(value: object) -> str:
    key = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    return DIMENSION_ALIASES.get(key, key if key in DIMENSION_ORDER else "")


def sanitize_question_payload(payload: dict, question_number: int) -> dict:
    should_continue = bool(payload.get("continue", True))
    if not should_continue:
        return {
            "continue": False,
            "question": "",
            "hint": "",
            "question_number": question_number,
            "dimension_probed": "",
            "reasoning": _clean_text(payload.get("reasoning"), 160) or "provider-stop",
        }

    question = _clean_text(payload.get("question"), 180)
    question = re.sub(r"^(q(uestion)?\s*\d+\s*[:.)-]\s*)", "", question, flags=re.I).strip("\"' ")
    if question and not question.endswith("?"):
        question = question.rstrip(".!") + "?"
    if not question or len(question.split()) > 24:
        raise ProviderError("Provider question was empty or too long")

    dimension = normalize_dimension(payload.get("dimension_probed"))
    if not dimension:
        raise ProviderError("Provider omitted a usable dimension")

    return {
        "continue": True,
        "question": question,
        "hint": _clean_text(payload.get("hint"), 180),
        "question_number": question_number,
        "dimension_probed": dimension,
        "reasoning": _clean_text(payload.get("reasoning"), 180) or "provider",
    }


def _tokens(text: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9']+", str(text or "").lower())
        if token not in STOPWORDS and len(token) > 2
    }


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def is_near_duplicate_question(candidate: str, asked_questions: Iterable[str]) -> bool:
    candidate_tokens = _tokens(candidate)
    candidate_norm = " ".join(sorted(candidate_tokens))
    for asked in asked_questions:
        asked_tokens = _tokens(asked)
        if candidate_norm and candidate_norm == " ".join(sorted(asked_tokens)):
            return True
        if _jaccard(candidate_tokens, asked_tokens) >= 0.62:
            return True
    return False


def _answer_signals(answers: Sequence[str]) -> Dict[str, int]:
    text = " ".join(answers).lower()

    def count(words):
        return sum(1 for word in words if word in text)

    return {
        "emotional_context": count(["sad", "happy", "joy", "angry", "nostalg", "melanch", "peace", "feel", "emotion", "heart"]),
        "movement_danceability": count(["dance", "groove", "move", "beat", "party", "body", "rhythm", "bounce"]),
        "tempo_energy": count(["fast", "slow", "hype", "energy", "calm", "electric", "loud", "soft", "workout", "warm"]),
        "lyric_vs_instrumental": count(["lyric", "word", "voice", "vocal", "instrumental", "sound", "texture", "melody"]),
        "listening_context": count(["alone", "friend", "drive", "commute", "night", "work", "study", "gym", "morning", "background"]),
    }


def _answer_is_specific(answer: str) -> bool:
    words = [word for word in str(answer or "").strip().split() if word]
    return len(words) >= 12 or bool(re.search(r"because|when|while|usually|especially|reminds|makes me|i feel", answer or "", re.I))


def should_stop_questioning(previous_answers: Sequence[str], covered_dimensions: Sequence[str]) -> bool:
    if len(previous_answers) < MIN_QUESTIONS:
        return False
    if len(previous_answers) >= MAX_QUESTIONS:
        return True
    if len(previous_answers) >= 3 and _answer_is_specific(previous_answers[-1]):
        return True
    if len(previous_answers) >= 4:
        return True
    return len(set(covered_dimensions)) >= 4 and len(previous_answers) >= 2


def choose_next_dimension(
    previous_answers: Sequence[str],
    covered_dimensions: Sequence[str],
    clip_ratings: Sequence[dict],
) -> Optional[str]:
    covered = {normalize_dimension(dim) for dim in covered_dimensions}
    uncovered = [dim for dim in DIMENSION_ORDER if dim not in covered]
    if not uncovered:
        return None
    if not previous_answers:
        active_clip_count = sum(1 for rating in clip_ratings if int(rating.get("rating") or 0) >= 4 or int(rating.get("rating") or 0) <= 2)
        if active_clip_count >= 3 and "emotional_context" in uncovered:
            return "emotional_context"
        return uncovered[0]

    signals = _answer_signals([previous_answers[-1]])
    strongest = max(signals.items(), key=lambda item: item[1])
    follow_ups = {
        "emotional_context": ["lyric_vs_instrumental", "listening_context", "movement_danceability"],
        "movement_danceability": ["tempo_energy", "emotional_context", "lyric_vs_instrumental"],
        "tempo_energy": ["movement_danceability", "listening_context", "lyric_vs_instrumental"],
        "lyric_vs_instrumental": ["movement_danceability", "tempo_energy", "listening_context"],
        "listening_context": ["emotional_context", "tempo_energy", "movement_danceability"],
    }
    if strongest[1] > 0:
        for dim in follow_ups[strongest[0]]:
            if dim in uncovered:
                return dim
    return uncovered[0]


def _stable_variant_index(seed_parts: Sequence[object], size: int) -> int:
    seed = "|".join(str(part) for part in seed_parts)
    value = sum(ord(ch) * (idx + 1) for idx, ch in enumerate(seed))
    return value % max(1, size)


class LocalQuestionProvider:
    provider_name = "local_fallback"

    def next_question(self, context: dict) -> dict:
        question_number = int(context.get("question_number") or 1)
        previous_answers = list(context.get("previous_answers") or [])
        clip_ratings = list(context.get("clip_ratings") or [])
        covered_dimensions = list(context.get("covered_dimensions") or [])
        asked_questions = list(context.get("asked_questions") or [])

        dimension = choose_next_dimension(previous_answers, covered_dimensions, clip_ratings)
        if not dimension:
            return {
                "continue": False,
                "question": "",
                "hint": "",
                "question_number": question_number,
                "dimension_probed": "",
                "reasoning": "local-complete",
                "provider": self.provider_name,
            }

        variants = QUESTION_BANK[dimension]
        start = _stable_variant_index(previous_answers + [dimension, question_number], len(variants))
        for offset in range(len(variants)):
            question, hint = variants[(start + offset) % len(variants)]
            if not is_near_duplicate_question(question, asked_questions):
                return {
                    "continue": True,
                    "question": question,
                    "hint": hint,
                    "question_number": question_number,
                    "dimension_probed": dimension,
                    "reasoning": "local-adaptive",
                    "provider": self.provider_name,
                }

        for fallback_dimension in DIMENSION_ORDER:
            if fallback_dimension in {normalize_dimension(dim) for dim in covered_dimensions}:
                continue
            question, hint = QUESTION_BANK[fallback_dimension][0]
            if not is_near_duplicate_question(question, asked_questions):
                return {
                    "continue": True,
                    "question": question,
                    "hint": hint,
                    "question_number": question_number,
                    "dimension_probed": fallback_dimension,
                    "reasoning": "local-adaptive",
                    "provider": self.provider_name,
                }

        return {
            "continue": False,
            "question": "",
            "hint": "",
            "question_number": question_number,
            "dimension_probed": "",
            "reasoning": "local-exhausted",
            "provider": self.provider_name,
        }


class GeminiQuestionProvider:
    provider_name = "gemini"

    def __init__(self, model: str = "gemini-2.5-flash"):
        self.model = model
        self.service = None
        try:
            from gemini_service import GeminiService
            self.service = GeminiService(model=model)
        except Exception as e:
            print(f"[adaptive.gemini_init_warn] {e}")

    @property
    def configured(self) -> bool:
        return bool(self.service and (self.service.api_key or self.service.client))

    def next_question(self, context: dict) -> dict:
        qnum = int(context.get("question_number") or 1)
        prev_answers = context.get("previous_answers") or []
        covered = context.get("covered_dimensions") or []
        asked = context.get("asked_questions") or []

        uncovered = [d for d in DIMENSION_ORDER if d not in covered]
        target_dim = uncovered[0] if uncovered else DIMENSION_ORDER[qnum % len(DIMENSION_ORDER)]

        import random
        angles = ["rhythm and movement", "nostalgic memory", "solitude and introspection", "physical sensation", "sonic texture and atmosphere", "lyrical storytelling", "social energy"]
        seed_angle = random.choice(angles)

        prompt = f"""Generate a unique, deeply evocative psychographic question about music listening habits. DO NOT repeat standard questions.
Question Number: {qnum}
Target Dimension to Probe: {target_dim}
Thematic Angle to Explore: {seed_angle}
Previous Answers: {json.dumps(prev_answers)}
Already Asked: {json.dumps(asked)}
Allowed Dimensions: {json.dumps(DIMENSION_ORDER)}

Return ONLY a valid JSON object matching this schema:
{{
  "continue": true,
  "question": "<short question under 18 words>",
  "hint": "<short clarifying prompt>",
  "question_number": {qnum},
  "dimension_probed": "{target_dim}",
  "reasoning": "<clinical psychological rationale>"
}}
"""
        if self.service and self.service.client:
            try:
                from google.genai import types
                from gemini_service import AdaptiveQuestionResponse
                config = types.GenerateContentConfig(
                    system_instruction="You are an expert cognitive music psychologist generating concise, highly unique, and deeply evocative adaptive questions. Avoid repeating any standard or previously asked questions. Output strictly as structured JSON.",
                    temperature=0.7,
                    response_mime_type="application/json",
                    response_schema=AdaptiveQuestionResponse,
                )
                res = self.service.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=config,
                )
                data = json.loads(res.text)
                return {
                    "continue": data.get("continue_questioning", True),
                    "question": data.get("question", ""),
                    "hint": data.get("hint", ""),
                    "question_number": qnum,
                    "dimension_probed": target_dim,
                    "reasoning": data.get("reasoning", "Gemini adaptive probing"),
                    "provider": self.provider_name,
                }
            except Exception as e:
                print(f"[adaptive.gemini_call_warn] {e}")

        # Local fallback if Gemini call fails
        fallbacks = {
            "emotional_context": ("What emotion does your go-to music usually carry?", "Joy, melancholy, hype, peace, or tension."),
            "movement_danceability": ("Does your favorite music make you move, or hold you still?", "Stillness vs full movement."),
            "tempo_energy": ("Do you reach for something fast and electric, or slow and warm?", "The default energy of your playlist."),
            "lyric_vs_instrumental": ("Are you there for the words, or the sound behind them?", "Lyrics vs immersive sound."),
            "listening_context": ("Where does music matter most in your day?", "Commute, late night, focus, or gym."),
        }
        q, h = fallbacks.get(target_dim, fallbacks["emotional_context"])
        return {
            "continue": True,
            "question": q,
            "hint": h,
            "question_number": qnum,
            "dimension_probed": target_dim,
            "reasoning": "Gemini psychometric rotation fallback",
            "provider": self.provider_name,
        }


class OpenRouterQuestionProvider:
    provider_name = "openrouter"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        requester: Callable = requests.post,
        timeout_seconds: Optional[float] = None,
        max_retries: Optional[int] = None,
    ):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.model = model or os.getenv("OPENROUTER_QUIZ_MODEL") or os.getenv("OPENROUTER_MODEL") or DEFAULT_OPENROUTER_MODEL
        self.requester = requester
        self.timeout_seconds = float(timeout_seconds if timeout_seconds is not None else os.getenv("OPENROUTER_TIMEOUT_SECONDS", "4.0"))
        self.max_retries = max(1, int(max_retries if max_retries is not None else os.getenv("OPENROUTER_MAX_RETRIES", "2")))

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _messages(self, context: dict) -> List[dict]:
        previous_answers = context.get("previous_answers") or []
        clip_ratings = context.get("clip_ratings") or []
        covered_dimensions = context.get("covered_dimensions") or []
        asked_questions = context.get("asked_questions") or []
        qnum = context.get("question_number") or 1
        return [
            {
                "role": "system",
                "content": (
                    "You generate one adaptive music-taste question as strict JSON. "
                    "Avoid repeated templates, avoid covered dimensions, and keep questions under 18 words."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "question_number": qnum,
                        "previous_answers": previous_answers,
                        "clip_ratings": clip_ratings,
                        "covered_dimensions": covered_dimensions,
                        "asked_questions": asked_questions,
                        "allowed_dimensions": DIMENSION_ORDER,
                        "response_schema": {
                            "continue": "boolean",
                            "question": "string",
                            "hint": "string",
                            "question_number": qnum,
                            "dimension_probed": "one allowed dimension",
                            "reasoning": "short string",
                        },
                    },
                    ensure_ascii=True,
                ),
            },
        ]

    def next_question(self, context: dict) -> dict:
        if not self.configured:
            raise ProviderError("OPENROUTER_API_KEY is not configured")

        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                response = self.requester(
                    OPENROUTER_CHAT_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": os.getenv("SONICDNA_FRONTEND_URL") or os.getenv("FRONTEND_URL") or "http://localhost",
                        "X-Title": "SonicDNA",
                    },
                    json={
                        "model": self.model,
                        "messages": self._messages(context),
                        "temperature": 0.65,
                        "max_tokens": 260,
                    },
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                payload = response.json()
                content = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content", "")
                result = sanitize_question_payload(_extract_json_object(content), int(context.get("question_number") or 1))
                result["provider"] = self.provider_name
                result["model"] = payload.get("model") or self.model
                return result
            except Exception as exc:
                last_error = exc
                if attempt + 1 < self.max_retries:
                    time.sleep(0.05 * (attempt + 1))

        raise ProviderError(str(last_error or "OpenRouter provider failed"))


class AdaptiveQuestionService:
    def __init__(self, provider=None, fallback_provider: Optional[LocalQuestionProvider] = None):
        self.provider = provider
        self.fallback_provider = fallback_provider or LocalQuestionProvider()

    @classmethod
    def from_env(cls) -> "AdaptiveQuestionService":
        gemini = GeminiQuestionProvider()
        if gemini.configured:
            return cls(provider=gemini)
        return cls(provider=OpenRouterQuestionProvider())

    def _context(
        self,
        previous_answers: Sequence[str],
        clip_ratings: Sequence[dict],
        covered_dimensions: Sequence[str],
        asked_questions: Sequence[str],
    ) -> dict:
        return {
            "question_number": len(previous_answers) + 1,
            "previous_answers": [_clean_text(answer, 500) for answer in previous_answers if str(answer or "").strip()],
            "clip_ratings": list(clip_ratings or []),
            "covered_dimensions": [normalize_dimension(dim) for dim in covered_dimensions if normalize_dimension(dim)],
            "asked_questions": [_clean_text(question, 220) for question in asked_questions if str(question or "").strip()],
        }

    def _valid_remote_result(self, result: dict, context: dict) -> bool:
        if not result.get("continue"):
            return True
        dimension = normalize_dimension(result.get("dimension_probed"))
        if not dimension or dimension in set(context["covered_dimensions"]):
            return False
        return not is_near_duplicate_question(result.get("question", ""), context["asked_questions"])

    def next_question(
        self,
        previous_answers: Sequence[str],
        clip_ratings: Sequence[dict],
        covered_dimensions: Sequence[str],
        asked_questions: Optional[Sequence[str]] = None,
    ) -> dict:
        context = self._context(previous_answers, clip_ratings, covered_dimensions, asked_questions or [])
        qnum = context["question_number"]
        if qnum > MAX_QUESTIONS or should_stop_questioning(context["previous_answers"], context["covered_dimensions"]):
            return {
                "continue": False,
                "question": "",
                "hint": "",
                "question_number": qnum,
                "dimension_probed": "",
                "reasoning": "enough-specific-signals",
                "provider": "rule_stop",
            }

        if self.provider is not None:
            try:
                result = self.provider.next_question(context)
                result = sanitize_question_payload(result, qnum)
                result["provider"] = getattr(self.provider, "provider_name", result.get("provider", "provider"))
                if self._valid_remote_result(result, context):
                    return result
            except Exception as exc:
                context["provider_error"] = str(exc)

        fallback = self.fallback_provider.next_question(context)
        fallback["duplicate_rejected"] = self.provider is not None and "provider_error" not in context
        if "provider_error" in context:
            fallback["provider_error"] = context["provider_error"]
        return fallback
