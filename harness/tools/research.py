from __future__ import annotations

import json
from html import unescape
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse


USER_AGENT = "Mozilla/5.0"


def _to_int(value: Any, default: int, minimum: int = 1, maximum: int = 50) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _clean_text(value: Any, max_chars: int | None = None) -> str:
    text = " ".join(str(value or "").split())
    if max_chars is not None and len(text) > max_chars:
        return text[:max_chars].rstrip() + "..."
    return text


def _duckduckgo_url(href: str) -> str:
    parsed = urlparse(href)
    query = parse_qs(parsed.query)
    if "uddg" in query and query["uddg"]:
        return query["uddg"][0]
    return href


def web_search(query: str, k: int = 5) -> list[dict[str, str]] | str:
    """Search DuckDuckGo's HTML endpoint and return result titles and URLs."""
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError as exc:
        pkg = "bs4" if exc.name == "bs4" else "requests"
        return f"error: 이 기능은 {pkg} 설치가 필요합니다."

    limit = _to_int(k, 5, 1, 20)
    try:
        response = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers={"User-Agent": USER_AGENT},
            timeout=20,
        )
        response.raise_for_status()
    except Exception as exc:
        return f"error: 웹 검색 실패: {exc}"

    soup = BeautifulSoup(response.text, "html.parser")
    results: list[dict[str, str]] = []
    for anchor in soup.select(".result__title a"):
        title = _clean_text(anchor.get_text(" "))
        href = anchor.get("href") or ""
        url = _duckduckgo_url(href)
        if title and url:
            results.append({"title": title, "url": url})
        if len(results) >= limit:
            break
    return results


def web_fetch(url: str, max_chars: int = 6000) -> str:
    """Fetch a web page and extract readable text with trafilatura."""
    try:
        import requests
        import trafilatura
    except ImportError as exc:
        pkg = "trafilatura" if exc.name == "trafilatura" else "requests"
        return f"error: 이 기능은 {pkg} 설치가 필요합니다."

    limit = _to_int(max_chars, 6000, 100, 50000)
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=25)
        response.raise_for_status()
        extracted = trafilatura.extract(response.text, url=url) or ""
    except Exception as exc:
        return f"error: 웹 문서 가져오기 실패: {exc}"

    text = extracted.strip()
    if len(text) > limit:
        return text[:limit].rstrip()
    return text


def _arxiv_search(requests: Any, query: str, limit: int) -> list[dict[str, str]] | str:
    try:
        import feedparser
    except ImportError:
        return "error: 이 기능은 feedparser 설치가 필요합니다."

    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": limit,
        "sortBy": "relevance",
    }
    url = "https://export.arxiv.org/api/query?" + urlencode(params)
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=25)
    response.raise_for_status()
    feed = feedparser.parse(response.text)
    results: list[dict[str, str]] = []
    for entry in feed.entries[:limit]:
        results.append(
            {
                "title": _clean_text(getattr(entry, "title", "")),
                "url": getattr(entry, "link", ""),
                "snippet": _clean_text(getattr(entry, "summary", ""), 500),
                "source": "arxiv",
            }
        )
    return results


def _s2_search(requests: Any, query: str, limit: int) -> list[dict[str, str]]:
    response = requests.get(
        "https://api.semanticscholar.org/graph/v1/paper/search",
        params={"query": query, "limit": limit, "fields": "title,url,abstract,paperId"},
        headers={"User-Agent": USER_AGENT},
        timeout=25,
    )
    response.raise_for_status()
    data = response.json()
    results: list[dict[str, str]] = []
    for item in data.get("data", [])[:limit]:
        paper_id = item.get("paperId") or ""
        url = item.get("url") or (f"https://www.semanticscholar.org/paper/{paper_id}" if paper_id else "")
        results.append(
            {
                "title": _clean_text(item.get("title", "")),
                "url": url,
                "snippet": _clean_text(item.get("abstract", ""), 500),
                "source": "s2",
            }
        )
    return results


def _openalex_abstract(index: dict[str, list[int]] | None) -> str:
    if not index:
        return ""
    words: list[tuple[int, str]] = []
    for word, positions in index.items():
        for position in positions:
            words.append((position, word))
    return " ".join(word for _, word in sorted(words))


def _openalex_search(requests: Any, query: str, limit: int) -> list[dict[str, str]]:
    response = requests.get(
        "https://api.openalex.org/works",
        params={"search": query, "per-page": limit},
        headers={"User-Agent": USER_AGENT},
        timeout=25,
    )
    response.raise_for_status()
    data = response.json()
    results: list[dict[str, str]] = []
    for item in data.get("results", [])[:limit]:
        primary = item.get("primary_location") or {}
        url = primary.get("landing_page_url") or item.get("id") or ""
        results.append(
            {
                "title": _clean_text(item.get("title", "")),
                "url": url,
                "snippet": _clean_text(_openalex_abstract(item.get("abstract_inverted_index")), 500),
                "source": "openalex",
            }
        )
    return results


def academic_search(query: str, k: int = 5, source: str = "arxiv") -> list[dict[str, str]] | str:
    """Search academic sources: arXiv, Semantic Scholar, OpenAlex, or all."""
    try:
        import requests
    except ImportError:
        return "error: 이 기능은 requests 설치가 필요합니다."

    limit = _to_int(k, 5, 1, 20)
    selected = str(source or "arxiv").lower()
    if selected not in {"arxiv", "s2", "openalex", "all"}:
        return "error: source는 arxiv|s2|openalex|all 중 하나여야 합니다."

    engines = ["arxiv", "s2", "openalex"] if selected == "all" else [selected]
    results: list[dict[str, str]] = []
    errors: list[str] = []
    per_engine = max(1, limit if selected != "all" else min(limit, 5))

    for engine in engines:
        try:
            if engine == "arxiv":
                found = _arxiv_search(requests, query, per_engine)
                if isinstance(found, str):
                    errors.append(found)
                    continue
            elif engine == "s2":
                found = _s2_search(requests, query, per_engine)
            else:
                found = _openalex_search(requests, query, per_engine)
            results.extend(found)
        except Exception as exc:
            errors.append(f"{engine}: {exc}")

    if results:
        return results[:limit] if selected != "all" else results[: max(limit, len(engines))]
    if errors:
        return "error: 학술 검색 실패: " + "; ".join(errors)
    return []


def _chat_text(messages: list[dict[str, str]], thinking: bool) -> str:
    from harness.llm_client import chat
    from harness.model_manager import manager

    response = chat(
        manager.active_base_url(),
        manager.model_name(),
        messages,
        thinking=thinking,
    )
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        for key in ("content", "text", "message", "response"):
            value = response.get(key)
            if isinstance(value, str):
                return value
        try:
            return json.dumps(response, ensure_ascii=False)
        except TypeError:
            return str(response)
    return str(response)


def _extract_queries(text: str, fallback: str, limit: int) -> list[str]:
    candidates: list[str] = []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            parsed = parsed.get("queries") or parsed.get("search_queries") or []
        if isinstance(parsed, list):
            candidates = [str(item).strip() for item in parsed if str(item).strip()]
    except Exception:
        candidates = []

    if not candidates:
        for raw_line in text.splitlines():
            line = raw_line.strip(" \t\r\n-0123456789.[]")
            if line:
                candidates.append(line)

    deduped: list[str] = []
    seen: set[str] = set()
    for query in candidates + [fallback]:
        key = query.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(query)
        if len(deduped) >= limit:
            break
    return deduped


def _source_digest(sources: list[dict[str, str]], max_chars: int = 6000) -> str:
    parts: list[str] = []
    for source in sources:
        text = source.get("text") or source.get("snippet") or ""
        parts.append(
            f"[{source['id']}] {source.get('title', '')}\n"
            f"URL: {source.get('url', '')}\n"
            f"EXCERPT: {_clean_text(text, 900)}"
        )
    digest = "\n\n".join(parts)
    return digest[:max_chars]


def _fallback_report(question: str, sources: list[dict[str, str]], reason: str | None = None) -> str:
    lines = [f"# Deep Research: {question}", ""]
    if reason:
        lines.extend([f"LLM 합성 단계 오류: {reason}", ""])
    if not sources:
        lines.append("error: 네트워크 검색 결과를 수집하지 못했습니다. requests/bs4/trafilatura/feedparser 설치와 네트워크 연결을 확인하세요.")
        return "\n".join(lines)
    lines.append("수집한 출처 요약:")
    for source in sources:
        excerpt = _clean_text(source.get("text") or source.get("snippet") or "", 600)
        lines.extend(
            [
                "",
                f"[{source['id']}] {source.get('title', '(제목 없음)')}",
                source.get("url", ""),
                excerpt,
            ]
        )
    return "\n".join(lines)


def deep_research(question: str, max_rounds: int = 2, sources_per_query: int = 3) -> str:
    """Plan, collect, analyze gaps, and synthesize a cited markdown report."""
    rounds = _to_int(max_rounds, 2, 1, 3)
    per_query = _to_int(sources_per_query, 3, 1, 5)
    max_sources = 12

    try:
        plan_text = _chat_text(
            [
                {
                    "role": "system",
                    "content": "You plan web and academic research. Return only a JSON array of concise search queries.",
                },
                {"role": "user", "content": question},
            ],
            thinking=True,
        )
    except Exception as exc:
        plan_text = ""
        plan_error = str(exc)
    else:
        plan_error = ""

    queries = _extract_queries(plan_text, question, max(2, per_query))
    sources: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for round_index in range(rounds):
        for query in queries:
            if len(sources) >= max_sources:
                break

            web_results = web_search(query, per_query)
            if isinstance(web_results, list):
                for result in web_results:
                    if len(sources) >= max_sources:
                        break
                    url = result.get("url", "")
                    if not url or url in seen_urls:
                        continue
                    fetched = web_fetch(url, 4000)
                    if isinstance(fetched, str) and fetched.startswith("error:"):
                        fetched = ""
                    seen_urls.add(url)
                    sources.append(
                        {
                            "id": str(len(sources) + 1),
                            "title": result.get("title", ""),
                            "url": url,
                            "text": fetched,
                            "source": "web",
                        }
                    )

            academic_results = academic_search(query, per_query, "all")
            if isinstance(academic_results, list):
                for result in academic_results:
                    if len(sources) >= max_sources:
                        break
                    url = result.get("url", "")
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    source = dict(result)
                    source["id"] = str(len(sources) + 1)
                    sources.append(source)

        if len(sources) >= max_sources or round_index >= rounds - 1:
            break

        try:
            gap_text = _chat_text(
                [
                    {
                        "role": "system",
                        "content": (
                            "Analyze the gathered sources for missing evidence. "
                            "Return only a JSON array of additional search queries."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Question: {question}\n\nSources:\n{_source_digest(sources)}",
                    },
                ],
                thinking=False,
            )
            queries = _extract_queries(gap_text, question, per_query)
        except Exception:
            queries = [question]

    if not sources:
        if plan_error:
            return f"error: deep_research 실행 실패: {plan_error}"
        return "error: 네트워크 검색 결과를 수집하지 못했습니다. requests/bs4/trafilatura/feedparser 설치와 네트워크 연결을 확인하세요."

    try:
        return _chat_text(
            [
                {
                    "role": "system",
                    "content": (
                        "Write a concise markdown research report in Korean. "
                        "Every factual claim that depends on the provided sources must cite sources as [n]. "
                        "Include a final 'Sources' section with the numbered URLs."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Question: {question}\n\nNumbered sources:\n{_source_digest(sources, 12000)}",
                },
            ],
            thinking=True,
        )
    except Exception as exc:
        return _fallback_report(question, sources, str(exc))


def register(registry: Any) -> None:
    registry.add(
        "web_search",
        "웹 검색 결과의 제목과 URL을 가져옵니다.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
        },
        web_search,
        permissions=(),
    )
    registry.add(
        "web_fetch",
        "웹 페이지 본문을 추출합니다.",
        {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "max_chars": {"type": "integer", "default": 6000, "minimum": 100},
            },
            "required": ["url"],
        },
        web_fetch,
        permissions=(),
    )
    registry.add(
        "academic_search",
        "arXiv, Semantic Scholar, OpenAlex에서 논문을 검색합니다.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
                "source": {"type": "string", "enum": ["arxiv", "s2", "openalex", "all"], "default": "arxiv"},
            },
            "required": ["query"],
        },
        academic_search,
        permissions=(),
    )
    registry.add(
        "deep_research",
        "검색, 수집, 갭 분석, 종합을 거쳐 인용이 포함된 리서치 보고서를 작성합니다.",
        {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "max_rounds": {"type": "integer", "default": 2, "minimum": 1, "maximum": 3},
                "sources_per_query": {"type": "integer", "default": 3, "minimum": 1, "maximum": 5},
            },
            "required": ["question"],
        },
        deep_research,
        permissions=(),
    )

