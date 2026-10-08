"""Causal world model components.

Numerical discovery (numpy/scipy/statsmodels) lives in
`sophia_episto.causal.discovery` and is an optional extra. Importing this
package does not load those libraries.
"""

from sophia_episto.causal.edge import CausalEdge, expert_priors
from sophia_episto.causal.graph import (
    CausalGraph,
    create_initial_graph,
    load_graph,
    save_graph,
)
from sophia_episto.causal.inference import (
    CausalInference,
    InferenceResult,
    query_causal_effect,
)

__all__ = [
    "CausalEdge",
    "CausalGraph",
    "CausalInference",
    "InferenceResult",
    "create_initial_graph",
    "expert_priors",
    "load_graph",
    "query_causal_effect",
    "save_graph",
]
