# Describes what went wrong in the pipeline; this is separate from HHTP.
# The API layer maps them to status codes and problem responses

from __future__ import annotations


class CtgovVizError(Exception):
    # This is the base class for every error this service raises

    #: Machine-readable code sent to the client.
    code = "internal_error"
    #: What the caller can do about it, if anything.
    remedy: str | None = None

    def __init__(self, message: str, *, remedy: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if remedy is not None:
            self.remedy = remedy


class ConfigurationError(CtgovVizError):
    # This error is given if the service is missing a configuration that it can't run without

    code = "configuration_error"


class UpstreamError(CtgovVizError):
    # This error is given if the ClinicalTrials.gov failed, timed out, or returned something that is unusable

    code = "upstream_error"
    remedy = "ClinicalTrials.gov may be temporarily unavailable; retry shortly."


class PlanningError(CtgovVizError):
    # This error is given if the planner couldn't produce a valid plan for this question

    code = "planning_error"
    remedy = "Try rephrasing the question, or supply structured filters directly."


class UnsupportedQueryError(CtgovVizError):
    # This error is given if the question is understood but it falls outside what this service can visualize (often means it is not a clinical trials question)

    code = "unsupported_query"


class AnalysisError(CtgovVizError):
    # This error is given if the validated plan couldn't be executed on the retrieved data

    code = "analysis_error"
