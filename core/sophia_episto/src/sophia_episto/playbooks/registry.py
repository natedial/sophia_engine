"""Playbook registry helpers."""

from sophia_episto.playbooks.base import Playbook
from sophia_episto.playbooks.labor_vs_growth import LaborVsGrowthPlaybook


def default_playbooks() -> list[Playbook]:
    return [
        LaborVsGrowthPlaybook(),
    ]
