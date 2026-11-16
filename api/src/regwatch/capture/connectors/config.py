"""``source.config`` and ``capture_job.extraction_rules`` per connector kind, as Pydantic models
that mirror docs/contracts/connectors.yaml (a contract test checks they agree).

The API validates on write with ``validate_config``; connectors read the parsed models. URLs in
a config are only checked for shape here; the source routes also run SafeFetcher's
``validate_source_url`` on them (M3 acceptance 3).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, ValidationError

from regwatch.core.errors import ProblemError, ProblemFieldError


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExtractionRules(_Strict):
    content_selectors: list[str] = []
    exclude_selectors: list[str] = []
    title_selector: str | None = None
    date_selector: str | None = None
    date_format: str | None = None
    include_url_patterns: list[str] = []
    exclude_url_patterns: list[str] = []
    strip_query_params: bool = True
    min_text_length: int = 200


class RssConfig(_Strict):
    feed_url: AnyUrl
    fetch_full_page: bool = True
    max_entries: int = Field(default=100, le=1000)
    etag_conditional: bool = True


class WebPageConfig(_Strict):
    page_url: AnyUrl
    mode: Literal["single", "listing"] = "single"
    listing_link_selector: str | None = None
    max_links: int = Field(default=50, le=500)
    wait_for_selector: str | None = None


class WebCrawlConfig(_Strict):
    seed_urls: list[AnyUrl] = Field(min_length=1, max_length=20)
    allowed_domains: list[str] = Field(min_length=1)
    max_depth: int = Field(default=3, le=5)
    max_pages_per_run: int = Field(default=200, le=2000)
    politeness_delay_seconds: float = Field(default=2, ge=0.5)
    follow_sitemaps: bool = False


class SearchQueryConfig(_Strict):
    query: str = Field(max_length=500)
    site_filters: list[str] = []
    languages: list[str] = []
    time_range: Literal["day", "week", "month", "year", "any"] = "month"
    max_results: int = Field(default=50, le=200)
    official_domains_only: bool = False


class ApiFeedConfig(_Strict):
    provider: Literal["federal_register", "eur_lex", "legislation_gov_uk", "generic_json"]
    params: dict[str, Any] = {}
    endpoint_url: AnyUrl | None = None
    item_path: str | None = None
    field_map: dict[str, str] = {}
    api_key_secret_name: str | None = None


class ManualConfig(_Strict):
    note: str | None = None


CONFIGS: dict[str, type[_Strict]] = {
    "rss": RssConfig,
    "web_page": WebPageConfig,
    "web_crawl": WebCrawlConfig,
    "search_query": SearchQueryConfig,
    "api_feed": ApiFeedConfig,
    "manual": ManualConfig,
}


def _problem(field: str, exc: ValidationError) -> ProblemError:
    errors = [
        ProblemFieldError(field=".".join([field, *(str(p) for p in e["loc"])]), message=e["msg"])
        for e in exc.errors(include_url=False)
    ]
    return ProblemError(422, "validation", "The connector settings are not valid.", errors=errors)


def validate_config(kind: str, config: dict[str, Any]) -> _Strict:
    """The parsed ``source.config`` for ``kind``, or a 422 naming every bad field."""
    model = CONFIGS.get(kind)
    if model is None:
        raise ProblemError(422, "validation", f"Unknown source kind {kind!r}.")
    try:
        return model.model_validate(config)
    except ValidationError as exc:
        raise _problem("config", exc) from None


def validate_rules(rules: dict[str, Any]) -> ExtractionRules:
    """The parsed ``capture_job.extraction_rules``, or a 422 naming every bad field."""
    try:
        return ExtractionRules.model_validate(rules)
    except ValidationError as exc:
        raise _problem("extraction_rules", exc) from None
