from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any

from app.core.cache import vault_cache
from app.core.config import Settings
from app.services.chunker import estimate_tokens
from app.services.prompts import (
    CUSTOM_SUMMARY_SYSTEM_PROMPT,
    DOCUMENT_INSIGHTS_SYSTEM_PROMPT,
    RAG_CHAT_SYSTEM_PROMPT,
)

STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "from", "are", "was", "were", "have",
    "has", "had", "not", "but", "you", "your", "can", "will", "should", "into", "about",
    "their", "they", "them", "been", "being", "also", "more", "than", "other", "which",
    "when", "where", "what", "who", "how", "why", "all", "any", "each", "use", "using",
    "used", "such", "may", "our", "out", "its", "per", "via", "these", "those", "over",
}

CATEGORY_KEYWORDS: dict[str, set[str]] = {
    "AI & Machine Learning": {"ai", "rag", "llm", "embeddings", "openai", "prompt", "vector", "gpt"},
    "Software Engineering": {"api", "backend", "fastapi", "async", "database", "postgresql", "redis", "celery", "architecture"},
    "Security & Compliance": {"security", "policy", "token", "auth", "encryption", "sha", "compliance", "access", "privacy"},
    "Finance & Operations": {"revenue", "cost", "budget", "quarter", "invoice", "pricing", "quota", "financial"},
    "Product & Case Study": {"product", "user", "deliverables", "mvp", "requirements", "roadmap", "evaluation", "demo"},
    "Legal & Contracts": {"agreement", "contract", "liability", "clause", "party", "terms", "jurisdiction"},
}

POSITIVE_WORDS = {"improve", "efficient", "accurate", "robust", "intelligent", "fast", "success", "excellence", "effective", "clean"}
NEGATIVE_WORDS = {"error", "fail", "failure", "risk", "violation", "breach", "invalid", "problem", "delay", "critical"}


@dataclass
class InsightGenerationResult:
    summary: str
    key_insights: list[str]
    categories: list[str]
    topics: list[str]
    sentiment: str
    model_used: str
    tokens_used: int
    estimated_cost_usd: float


@dataclass
class CustomSummaryResult:
    summary: str
    model_used: str
    tokens_used: int
    estimated_cost_usd: float
    cached: bool = False


@dataclass
class RagGenerationResult:
    answer: str
    follow_up_questions: list[str]
    model_used: str
    tokens_used: int
    estimated_cost_usd: float
    cached: bool = False


def tokenize_words(text: str) -> list[str]:
    return [
        w for w in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", text.lower())
        if w not in STOPWORDS
    ]


def local_embed_text(text: str, dim: int = 256) -> list[float]:
    """Deterministic feature-hashing vector over word unigrams, bigrams, and char n-grams."""
    vec = [0.0] * dim
    words = tokenize_words(text)
    if not words:
        words = re.findall(r"\w+", text.lower()) or ["empty"]

    features: list[tuple[str, float]] = []
    counts = Counter(words)
    for word, cnt in counts.items():
        tf = 1.0 + math.log(cnt)
        features.append((f"w:{word}", tf * 1.5))
        if len(word) >= 4:
            features.append((f"p:{word[:4]}", tf * 0.6))

    for i in range(len(words) - 1):
        features.append((f"b:{words[i]}_{words[i + 1]}", 1.2))

    for feat, weight in features:
        digest = hashlib.md5(feat.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:2], "little") % dim
        sign = 1.0 if (digest[2] & 1) == 0 else -1.0
        vec[idx] += sign * weight

    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [round(v / norm, 6) for v in vec]


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    return sum(a * b for a, b in zip(vec_a, vec_b))


class AIProviderError(RuntimeError):
    """Structured upstream AI provider error (e.g. token/credit exhaustion, rate limit)."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _call_provider(fn):
    from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

    try:
        return fn()
    except RateLimitError as exc:
        raise AIProviderError(
            429,
            "You exhausted your token limits with the AI provider. Please wait for rate limits to reset or switch to local mode.",
        ) from exc
    except APIStatusError as exc:
        msg = str(exc)
        lowered = msg.lower()
        if exc.status_code in (402, 429) or any(
            kw in lowered for kw in ("credit", "quota", "token", "limit", "insufficient", "afford")
        ):
            raise AIProviderError(
                429 if exc.status_code == 429 else 402,
                "You exhausted your token limits or credits with the AI provider. Please add credits or switch to local mode.",
            ) from exc
        raise AIProviderError(502, f"AI provider error ({exc.status_code}): {msg}") from exc
    except (APIConnectionError, APITimeoutError) as exc:
        raise AIProviderError(504, f"AI provider connection/timeout error: {exc}") from exc


def build_llm_client(settings: Settings):
    """Build an OpenAI-compatible client configured for OpenRouter or OpenAI."""
    from openai import OpenAI

    if settings.openrouter_api_key:
        return OpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            default_headers={
                "HTTP-Referer": settings.openrouter_site_url,
                "X-Title": settings.openrouter_site_name,
            },
        )
    return OpenAI(api_key=settings.openai_api_key)


def _parse_json_object(raw_content: str | None) -> dict[str, Any]:
    if not raw_content:
        return {}
    cleaned = raw_content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return {}
        return {}


def _extract_usage_cost(usage: Any, fallback_tokens: int, rate_per_million: float) -> tuple[int, float]:
    tokens = getattr(usage, "total_tokens", 0) or fallback_tokens
    provider_cost = getattr(usage, "cost", None)
    if provider_cost is not None:
        return int(tokens), round(float(provider_cost), 8)
    return int(tokens), round((tokens / 1_000_000) * rate_per_million, 8)


def embed_texts(texts: list[str], settings: Settings) -> tuple[list[list[float]], int, float]:
    """Embed batch of strings with caching; uses OpenRouter/OpenAI if configured, else local hashing."""
    results: list[list[float] | None] = [None] * len(texts)
    missing_indices: list[int] = []
    emb_ns = f"emb:{settings.ai_mode}:{settings.active_embedding_model}"

    for i, text in enumerate(texts):
        cache_key = vault_cache.make_key(emb_ns, text)
        cached = vault_cache.get(cache_key)
        if cached is not None:
            results[i] = cached
        else:
            missing_indices.append(i)

    tokens_used = 0
    cost_usd = 0.0

    if missing_indices:
        if settings.has_llm:
            client = build_llm_client(settings)
            batch_inputs = [texts[i] for i in missing_indices]
            resp = _call_provider(
                lambda: client.embeddings.create(
                    model=settings.active_embedding_model,
                    input=batch_inputs,
                )
            )
            fallback_tok = sum(estimate_tokens(t) for t in batch_inputs)
            tokens_used, cost_usd = _extract_usage_cost(resp.usage, fallback_tok, 0.02)
            for idx, item in zip(missing_indices, resp.data):
                vec = list(item.embedding)
                results[idx] = vec
                vault_cache.set(vault_cache.make_key(emb_ns, texts[idx]), vec)
        else:
            for idx in missing_indices:
                vec = local_embed_text(texts[idx])
                results[idx] = vec
                vault_cache.set(vault_cache.make_key(emb_ns, texts[idx]), vec)

    return [r or [] for r in results], tokens_used, cost_usd


def _rank_sentences(text: str, focus_terms: set[str] | None = None) -> list[str]:
    raw_sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    candidates = [
        re.sub(r"^[\-\*\u2022\ufffd\d.)\s]+", "", s).strip()
        for s in raw_sentences
        if len(s.strip()) >= 35
    ]
    if not candidates:
        candidates = [s.strip() for s in raw_sentences if len(s.strip()) >= 15]
    if not candidates:
        return [text[:300].strip()] if text.strip() else ["No content available."]

    word_freq = Counter(tokenize_words(text))
    scored: list[tuple[float, int, str]] = []
    seen: set[str] = set()
    for pos, sent in enumerate(candidates):
        norm_key = sent.lower()[:80]
        if norm_key in seen:
            continue
        seen.add(norm_key)
        words = tokenize_words(sent)
        if not words:
            continue
        score = sum(word_freq[w] for w in set(words)) / (len(words) ** 0.65)
        if pos < 3:
            score *= 1.25  # Early overview sentences carry strong summary signal
        if focus_terms and (set(words) & focus_terms):
            score *= 1.8
        scored.append((score, pos, sent))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [s for _score, _pos, s in scored]


def _local_generate_insights(text: str) -> InsightGenerationResult:
    ranked = _rank_sentences(text)
    summary_sents = ranked[:3]
    summary = " ".join(
        s if s.endswith((".", "!", "?")) else f"{s}." for s in summary_sents
    )
    key_insights = [
        (s if s.endswith((".", "!", "?")) else f"{s}.")
        for s in ranked[:5]
    ]

    words = tokenize_words(text)
    freq = Counter(words)
    topics = [w for w, _ in freq.most_common(6)]

    word_set = set(words)
    matched_cats: list[tuple[int, str]] = []
    for cat, kw in CATEGORY_KEYWORDS.items():
        overlap = len(word_set & kw)
        if overlap > 0:
            matched_cats.append((overlap, cat))
    matched_cats.sort(reverse=True)
    categories = [cat for _, cat in matched_cats[:3]] or ["General Document"]

    pos_hits = sum(freq[w] for w in POSITIVE_WORDS)
    neg_hits = sum(freq[w] for w in NEGATIVE_WORDS)
    if pos_hits > neg_hits + 2:
        sentiment = "positive"
    elif neg_hits > pos_hits + 2:
        sentiment = "negative"
    else:
        sentiment = "neutral"

    return InsightGenerationResult(
        summary=summary,
        key_insights=key_insights,
        categories=categories,
        topics=topics,
        sentiment=sentiment,
        model_used="local-extractive-v1",
        tokens_used=estimate_tokens(text[:6000]),
        estimated_cost_usd=0.0,
    )


def generate_document_insights(text: str, settings: Settings) -> InsightGenerationResult:
    excerpt = text[:12000]
    if settings.has_llm:
        client = build_llm_client(settings)
        model_name = settings.active_chat_model
        resp = _call_provider(
            lambda: client.chat.completions.create(
                model=model_name,
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=900,
                messages=[
                    {"role": "system", "content": DOCUMENT_INSIGHTS_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Document content:\n\n{excerpt}"},
                ],
            )
        )
        data = _parse_json_object(resp.choices[0].message.content)
        rate = 2.50 if "gpt-4o" in model_name and "mini" not in model_name else 0.30
        tokens, cost = _extract_usage_cost(resp.usage, estimate_tokens(excerpt), rate)
        return InsightGenerationResult(
            summary=data.get("summary") or "Summary unavailable.",
            key_insights=list(data.get("key_insights") or [])[:5],
            categories=list(data.get("categories") or ["General Document"])[:3],
            topics=list(data.get("topics") or [])[:6],
            sentiment=str(data.get("sentiment") or "neutral").lower(),
            model_used=model_name,
            tokens_used=tokens,
            estimated_cost_usd=cost,
        )

    return _local_generate_insights(excerpt)


def generate_custom_summary(
    text: str,
    length: str,
    focus: str,
    tone: str,
    settings: Settings,
) -> CustomSummaryResult:
    cache_key = vault_cache.make_key(
        f"sum:{settings.ai_mode}:{settings.active_chat_model}",
        {"h": hashlib.sha256(text[:10000].encode("utf-8")).hexdigest(), "l": length, "f": focus, "t": tone},
    )
    cached = vault_cache.get(cache_key)
    if cached is not None:
        return CustomSummaryResult(**cached, cached=True)

    excerpt = text[:12000]
    if settings.has_llm:
        client = build_llm_client(settings)
        model_name = settings.active_chat_model
        system_prompt = CUSTOM_SUMMARY_SYSTEM_PROMPT.format(length=length, focus=focus, tone=tone)
        resp = _call_provider(
            lambda: client.chat.completions.create(
                model=model_name,
                temperature=0.2,
                max_tokens=900,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": excerpt},
                ],
            )
        )
        summary_text = (resp.choices[0].message.content or "").strip()
        rate = 2.50 if "gpt-4o" in model_name and "mini" not in model_name else 0.30
        tokens, cost = _extract_usage_cost(resp.usage, estimate_tokens(excerpt), rate)
        payload = {
            "summary": summary_text,
            "model_used": model_name,
            "tokens_used": tokens,
            "estimated_cost_usd": cost,
        }
        vault_cache.set(cache_key, payload)
        return CustomSummaryResult(**payload, cached=False)

    focus_map = {
        "technical": {"api", "architecture", "database", "async", "pipeline", "rag", "vector", "model", "code"},
        "action_items": {"must", "required", "deliverables", "build", "implement", "create", "ensure", "mandatory"},
        "risks": {"error", "fail", "limit", "security", "expire", "risk", "edge", "fallback"},
        "general": set(),
    }
    count_map = {"short": 2, "medium": 4, "detailed": 6}
    n_sents = count_map.get(length, 4)
    ranked = _rank_sentences(excerpt, focus_terms=focus_map.get(focus, set()))[:n_sents]

    prefix_map = {
        "executive": "Executive Brief: ",
        "simple": "In plain terms: ",
        "professional": "",
    }
    prefix = prefix_map.get(tone, "")
    if length == "detailed":
        body = "\n".join(f"- {s if s.endswith('.') else s + '.'}" for s in ranked)
        summary_text = f"{prefix}\n{body}".strip() if prefix else body
    else:
        joined = " ".join(s if s.endswith((".", "!", "?")) else f"{s}." for s in ranked)
        summary_text = f"{prefix}{joined}".strip()

    payload = {
        "summary": summary_text,
        "model_used": "local-extractive-v1",
        "tokens_used": estimate_tokens(summary_text),
        "estimated_cost_usd": 0.0,
    }
    vault_cache.set(cache_key, payload)
    return CustomSummaryResult(**payload, cached=False)


def generate_grounded_rag_answer(
    question: str,
    history: list[dict[str, str]],
    contexts: list[dict[str, Any]],
    settings: Settings,
) -> RagGenerationResult:
    """Generate a citation-grounded answer + follow-up questions from retrieved chunks."""
    if not contexts:
        return RagGenerationResult(
            answer=(
                "I couldn't find information about that in your uploaded documents. "
                "I can help you with something else related to your vault—try asking about the topics covered in your files."
            ),
            follow_up_questions=[
                "What topics are covered in the uploaded documents?",
                "Can you summarize the main document?",
            ],
            model_used=settings.active_chat_model,
            tokens_used=0,
            estimated_cost_usd=0.0,
        )

    cache_key = vault_cache.make_key(
        f"rag:v3:{settings.ai_mode}:{settings.active_chat_model}",
        {
            "q": question.strip().lower(),
            "h": [m["content"] for m in history[-2:]],
            "c": [(c["document_id"], c["chunk_index"]) for c in contexts],
        },
    )
    cached = vault_cache.get(cache_key)
    if cached is not None:
        return RagGenerationResult(**cached, cached=True)

    context_block = "\n\n".join(
        f"[Source {idx}] (Document: {c['filename']}, Page {c['page_number']}):\n{c['content']}"
        for idx, c in enumerate(contexts, start=1)
    )

    if settings.has_llm:
        client = build_llm_client(settings)
        model_name = settings.active_chat_model
        messages: list[dict[str, str]] = [{"role": "system", "content": RAG_CHAT_SYSTEM_PROMPT}]
        for turn in history[-6:]:
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append(
            {
                "role": "user",
                "content": f"Context Excerpts:\n{context_block}\n\nQuestion: {question}",
            }
        )
        resp = _call_provider(
            lambda: client.chat.completions.create(
                model=model_name,
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=1000,
                messages=messages,  # type: ignore[arg-type]
            )
        )
        raw_text = resp.choices[0].message.content or ""
        parsed = _parse_json_object(raw_text)
        rate = 2.50 if "gpt-4o" in model_name and "mini" not in model_name else 0.30
        tokens, cost = _extract_usage_cost(
            resp.usage, estimate_tokens(context_block + question), rate
        )
        payload = {
            "answer": parsed.get("answer") or raw_text.strip() or "Unable to synthesize answer.",
            "follow_up_questions": list(parsed.get("follow_up_questions") or [])[:3],
            "model_used": model_name,
            "tokens_used": tokens,
            "estimated_cost_usd": cost,
        }
        vault_cache.set(cache_key, payload)
        return RagGenerationResult(**payload, cached=False)

    # Local grounded synthesis with exact [Source N] inline attributions
    q_terms = set(tokenize_words(question))
    for turn in history[-2:]:
        if turn["role"] == "user":
            q_terms.update(tokenize_words(turn["content"])[:4])

    # If none of the query terms appear in any retrieved chunk and dense score is low, refuse off-topic query
    max_term_overlap = max(
        (len(set(tokenize_words(ctx["content"])) & q_terms) for ctx in contexts[:4]),
        default=0,
    )
    max_score = max((float(ctx.get("score", 0.0)) for ctx in contexts[:4]), default=0.0)
    if q_terms and max_term_overlap == 0 and max_score < 0.25:
        all_ctx_words = tokenize_words(" ".join(c["content"] for c in contexts[:3]))
        top_terms = [w for w, _ in Counter(all_ctx_words).most_common(4)]
        suggestions = [f"What does the document say about {t}?" for t in top_terms[:2]] or [
            f"Can you summarize {contexts[0]['filename']}?"
        ]
        payload = {
            "answer": (
                "I couldn't find information about that in your uploaded documents, so I can't answer it from your vault. "
                "I can help you with something else related to your uploaded documents—try asking about one of the topics covered in them."
            ),
            "follow_up_questions": suggestions,
            "model_used": "local-rag-v1",
            "tokens_used": estimate_tokens(question),
            "estimated_cost_usd": 0.0,
        }
        vault_cache.set(cache_key, payload)
        return RagGenerationResult(**payload, cached=False)

    evidence_points: list[str] = []
    seen_snippets: set[str] = set()
    for src_idx, ctx in enumerate(contexts[:4], start=1):
        sents = re.split(r"(?<=[.!?])\s+|\n+", ctx["content"])
        best_sents: list[tuple[float, str]] = []
        for s in sents:
            clean = re.sub(r"^[\-\*\u2022\ufffd]+\s*", "", s).strip()
            if len(clean) < 20:
                continue
            s_words = set(tokenize_words(clean))
            overlap = len(s_words & q_terms)
            score = overlap * 2.5 + min(len(s_words), 15) * 0.1
            best_sents.append((score, clean))
        best_sents.sort(key=lambda x: x[0], reverse=True)
        for _sc, chosen in best_sents[:2]:
            sig = chosen.lower()[:60]
            if sig not in seen_snippets:
                seen_snippets.add(sig)
                ending = "" if chosen.endswith((".", "!", "?")) else "."
                evidence_points.append(f"{chosen}{ending} [Source {src_idx}]")
        if len(evidence_points) >= 4:
            break

    if not evidence_points:
        snippet = contexts[0]["content"][:260].strip()
        evidence_points.append(f"{snippet} [Source 1]")

    answer = "Based on the uploaded vault documents:\n\n" + "\n".join(
        f"- {pt}" for pt in evidence_points
    )

    # Generate context-aware follow-up suggestions from top chunk topics
    all_ctx_words = tokenize_words(" ".join(c["content"] for c in contexts[:3]))
    top_terms = [w for w, _ in Counter(all_ctx_words).most_common(6) if w not in q_terms]
    follow_ups: list[str] = []
    if top_terms:
        follow_ups.append(f"What does the document specify about {top_terms[0]}?")
    if len(top_terms) > 1:
        follow_ups.append(f"How are {top_terms[0]} and {top_terms[1]} related in this context?")
    if len({c["document_id"] for c in contexts}) > 1:
        follow_ups.append("What are the key differences across the referenced documents?")
    else:
        follow_ups.append(f"Can you provide a detailed summary of {contexts[0]['filename']}?")

    payload = {
        "answer": answer,
        "follow_up_questions": follow_ups[:3],
        "model_used": "local-rag-v1",
        "tokens_used": estimate_tokens(context_block + question),
        "estimated_cost_usd": 0.0,
    }
    vault_cache.set(cache_key, payload)
    return RagGenerationResult(**payload, cached=False)
