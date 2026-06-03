"""SLA metric tools (2) — faithful port of the ITSM MCP's sla_metrics category.

Aggregations over ``sla_definition.target_mins`` grouped by priority. The MCP keys its result
by the *uppercased* requested priority and matches that uppercased value against the stored
``applies_to_priority`` column. Both tools return ``{"metrics": {<PRIORITY>: value}}``. With no
``priority`` filter the result is an empty metrics object. Verified against the live MCP by the
differential conformance test.
"""

from __future__ import annotations

from typing import List, Optional

from eops_gym.domains.itsm.tools._base import ItsmToolsBase
from eops_gym.environment.toolkit import ToolType, is_tool


class SLAMetricToolsMixin(ItsmToolsBase):
    """SLA metric aggregation tools."""

    def _target_mins_for(self, priority_upper: str) -> List[int]:
        """target_mins of every sla_definition whose applies_to_priority equals the key.

        The MCP compares the (uppercased) requested priority directly against the stored
        ``applies_to_priority`` value, so seeds that store lowercase priorities yield no matches.
        """
        return [
            sla.target_mins
            for sla in self.db.sla_definition.values()
            if sla.applies_to_priority == priority_upper
        ]

    @is_tool(ToolType.READ)
    def total_sum_of_target_mins_per_priority(
        self, priority: Optional[List[str]] = None
    ) -> dict:
        """Compute the total sum of target minutes grouped by priority.

        Args:
            priority: Optional list of priorities to filter by. Accepted values: critical, high,
                moderate, low. When omitted, the metrics object is empty.

        Returns:
            An object ``{"metrics": {<PRIORITY>: sum}}`` keyed by the uppercased priority, where
            each value is the summed target minutes of matching SLA definitions.
        """
        metrics: dict = {}
        for p in priority or []:
            key = p.upper()
            metrics[key] = sum(self._target_mins_for(key))
        return {"metrics": metrics}

    @is_tool(ToolType.READ)
    def average_target_mins_per_priority(
        self, priority: Optional[List[str]] = None
    ) -> dict:
        """Compute the average of target minutes grouped by priority.

        Args:
            priority: Optional list of priorities to filter by. Accepted values: critical, high,
                moderate, low. When omitted, the metrics object is empty.

        Returns:
            An object ``{"metrics": {<PRIORITY>: average}}`` keyed by the uppercased priority,
            where each value is the average target minutes of matching SLA definitions rounded to
            two decimal places (0.0 when there are no matches).
        """
        metrics: dict = {}
        for p in priority or []:
            key = p.upper()
            values = self._target_mins_for(key)
            metrics[key] = round(sum(values) / len(values), 2) if values else 0.0
        return {"metrics": metrics}
