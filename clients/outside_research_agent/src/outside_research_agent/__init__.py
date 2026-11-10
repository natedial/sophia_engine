"""Outside research agent: coordinates Analyst and Sophia public surfaces.

This package is not part of Episto. It must not import Analyst or Sophia
internal models, and those packages must not import this one.
"""

from outside_research_agent.analyst import (
    AnalystUnavailable,
    IncompleteAnalystOutput,
    TransportResult,
    extract_claims,
    load_analyst_payload,
)
from outside_research_agent.sophia import SophiaCli, SophiaProtocolError
from outside_research_agent.workflow import resume_case, run_case

__all__ = [
    "AnalystUnavailable",
    "IncompleteAnalystOutput",
    "SophiaCli",
    "SophiaProtocolError",
    "TransportResult",
    "extract_claims",
    "load_analyst_payload",
    "resume_case",
    "run_case",
]
