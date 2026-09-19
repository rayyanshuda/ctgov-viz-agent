# Async client for the ClinicalTrials.gov API

# Retries, pagination, asking for only the fields needed, caching, and recording the parameters of every request

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.cache import ResponseCache, cache_key
from app.config import Settings
from app.ctgov.normalize import TrialRecord, normalize_study
from app.ctgov.query_builder import build_params
from app.errors import UpstreamError
from app.models.plan import TrialFilterSpec

logger = logging.getLogger(__name__)

STUDIES_PATH = "/studies"

# Always requested, because every citation needs an ID and a title to quote
BASE_FIELDS: tuple[str, ...] = ("NCTId", "BriefTitle")

_RETRYABLE_STATUS = {403, 429, 500, 502, 503, 504}


@dataclass
class FetchResult:
    # The records fetched for one cohort, plus what it took to get them

    records: list[TrialRecord]
    total_count: int
    # How many studies the API says match, which can be more than actually fetched

    truncated: bool
    # True when the cap stopped us before reaching total_count

    requests: list[dict[str, str]] = field(default_factory=list)
    # The parameters sent, so the result can be reproduced

    @property
    def analyzed_count(self) -> int:
        return len(self.records)


class CTGovClient:
    # A retrying caching wrapper around the study search endpoint

    def __init__(
        self,
        settings: Settings,
        cache: ResponseCache | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self.cache = cache or ResponseCache(
            settings.cache_dir, settings.cache_ttl_seconds, settings.cache_enabled
        )
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> CTGovClient:
        self._ensure_client()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.settings.ctgov_base_url,
                timeout=self.settings.http_timeout_seconds,
                headers={
                    "Accept": "application/json",
                    "Accept-Language": "en-US,en;q=0.9",
                    "User-Agent": self.settings.ctgov_user_agent,
                },
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None


# transport

    async def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        # GET with caching, retries and backoff. Raises UpstreamError if it gives up
        key = cache_key(path, params)
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        client = self._ensure_client()
        last_error: str = "unknown error"

        for attempt in range(self.settings.http_max_retries):
            try:
                response = await client.get(path, params=params)
            except httpx.TimeoutException:
                last_error = f"request timed out after {self.settings.http_timeout_seconds}s"
            except httpx.HTTPError as exc:
                last_error = f"network error: {exc}"
            else:
                if response.status_code == 200:
                    try:
                        payload = response.json()
                    except ValueError as exc:
                        raise UpstreamError(
                            f"ClinicalTrials.gov returned a non-JSON response: {exc}"
                        ) from exc
                    self.cache.set(key, payload)
                    return payload

                if response.status_code == 400:
                    # A malformed query is our bug: fail with the API's own explanation instead of retrying three times.
                    raise UpstreamError(
                        "ClinicalTrials.gov rejected the query: "
                        f"{response.text[:300].strip()}",
                        remedy="This indicates a malformed filter; please report the query.",
                    )
                if response.status_code not in _RETRYABLE_STATUS:
                    raise UpstreamError(
                        f"ClinicalTrials.gov returned HTTP {response.status_code}: "
                        f"{response.text[:200].strip()}"
                    )
                last_error = f"HTTP {response.status_code}"

            if attempt < self.settings.http_max_retries - 1:
                # Exponential backoff
                delay = (2**attempt) * 0.5 + random.uniform(0, 0.25)
                logger.info(
                    "Retrying ClinicalTrials.gov request in %.2fs (%s)", delay, last_error
                )
                await asyncio.sleep(delay)

        if last_error == "HTTP 403":
            # Telling the caller to "retry shortly" here would be wrong: a sustained 403
            # is the upstream WAF refusing this source address, not a passing blip.
            raise UpstreamError(
                "ClinicalTrials.gov refused this request with HTTP 403 after "
                f"{self.settings.http_max_retries} attempts. Its WAF blocks some "
                "datacenter IP ranges, so a cloud-hosted deployment can be refused while "
                "the identical request succeeds from a laptop.",
                remedy="Run the service locally, or deploy somewhere whose outbound IP "
                "range is not blocked. Retrying from the same host is unlikely to help.",
            )
        raise UpstreamError(
            f"ClinicalTrials.gov request failed after {self.settings.http_max_retries} "
            f"attempts: {last_error}"
        )


# operations

    async def count(self, filters: TrialFilterSpec, extra_advanced: str | None = None) -> int:
        # How many studies match, while downloading one of them.
        # Can also ask the API because it's what powers the planner's size probe and the exact-count strategy.
        params = build_params(
            filters,
            fields=["NCTId"],
            page_size=1,
            count_total=True,
            extra_advanced=extra_advanced,
        )
        payload = await self._get(STUDIES_PATH, params)
        return int(payload.get("totalCount", 0))

    async def count_and_sample(
        self,
        filters: TrialFilterSpec,
        *,
        extra_advanced: str | None = None,
        sample_size: int = 3,
        fields: Sequence[str] = (),
        cohort: str = "",
    ) -> tuple[int, list[TrialRecord], dict[str, str]]:
        # Get a match count and a few example records in a single request.
        # countTotal and pageSize are independent, so asking for three records still
        # returns the true total for the whole result set. So one request per bucket gives both the number to
        # plot and the trials to cite for it, without downloading everything.
        projection = tuple(dict.fromkeys([*BASE_FIELDS, *fields]))
        params = build_params(
            filters,
            fields=projection,
            page_size=max(sample_size, 1),
            count_total=True,
            extra_advanced=extra_advanced,
        )
        payload = await self._get(STUDIES_PATH, params)
        records = [
            record
            for study in (payload.get("studies") or [])
            if (record := normalize_study(study, cohort=cohort)) is not None
        ]
        return int(payload.get("totalCount", 0)), records, params

    async def fetch(
        self,
        filters: TrialFilterSpec,
        *,
        fields: Sequence[str],
        max_studies: int,
        cohort: str = "",
    ) -> FetchResult:
        # Page through matching studies, normalizing them as it goes.
        # Stops at max_studies and flags truncated, instead of analyzing a
        # partial set as if it was the whole thing.
        projection = tuple(dict.fromkeys([*BASE_FIELDS, *fields]))
        records: list[TrialRecord] = []
        requests: list[dict[str, str]] = []
        page_token: str | None = None
        total_count = 0
        first_page = True

        while len(records) < max_studies:
            remaining = max_studies - len(records)
            params = build_params(
                filters,
                fields=projection,
                page_size=min(self.settings.page_size, remaining),
                count_total=first_page,
                page_token=page_token,
            )
            payload = await self._get(STUDIES_PATH, params)
            requests.append(params)

            if first_page:
                total_count = int(payload.get("totalCount", 0))
                first_page = False

            studies = payload.get("studies") or []
            for study in studies:
                record = normalize_study(study, cohort=cohort)
                if record is not None:
                    records.append(record)

            page_token = payload.get("nextPageToken")
            if not page_token or not studies:
                break

        return FetchResult(
            records=records,
            total_count=total_count,
            truncated=total_count > len(records),
            requests=requests,
        )
