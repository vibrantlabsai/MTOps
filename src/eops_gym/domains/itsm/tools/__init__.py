"""ITSM toolkit — combines all 19 category mixins into one ``ItsmTools`` toolkit.

The toolkit metaclass collects every ``@is_tool`` method across the MRO, giving the full
93-tool ITSM action space. Each mixin lives in its own module mirroring the original MCP's
tool categories.
"""

from eops_gym.domains.itsm.tools._base import ItsmError, ItsmToolsBase
from eops_gym.domains.itsm.tools.change_request_mappings import ChangeRequestMappingToolsMixin
from eops_gym.domains.itsm.tools.changes import ChangeToolsMixin
from eops_gym.domains.itsm.tools.configuration_items import ConfigurationItemToolsMixin
from eops_gym.domains.itsm.tools.groups import GroupToolsMixin
from eops_gym.domains.itsm.tools.incident_affected_cis import IncidentAffectedCIToolsMixin
from eops_gym.domains.itsm.tools.incident_knowledges import IncidentKnowledgeToolsMixin
from eops_gym.domains.itsm.tools.incident_slas import IncidentSLAToolsMixin
from eops_gym.domains.itsm.tools.incident_templates import IncidentTemplateToolsMixin
from eops_gym.domains.itsm.tools.incidents import IncidentToolsMixin
from eops_gym.domains.itsm.tools.knowledge import KnowledgeToolsMixin
from eops_gym.domains.itsm.tools.locations import LocationToolsMixin
from eops_gym.domains.itsm.tools.notification_analysis import NotificationAnalysisToolsMixin
from eops_gym.domains.itsm.tools.notifications import NotificationToolsMixin
from eops_gym.domains.itsm.tools.problems import ProblemToolsMixin
from eops_gym.domains.itsm.tools.service_offerings import ServiceOfferingToolsMixin
from eops_gym.domains.itsm.tools.services import ServiceToolsMixin
from eops_gym.domains.itsm.tools.sla_definitions import SLADefinitionToolsMixin
from eops_gym.domains.itsm.tools.sla_metrics import SLAMetricToolsMixin
from eops_gym.domains.itsm.tools.users import UserToolsMixin


class ItsmTools(
    IncidentToolsMixin,
    UserToolsMixin,
    GroupToolsMixin,
    LocationToolsMixin,
    ConfigurationItemToolsMixin,
    ServiceToolsMixin,
    ServiceOfferingToolsMixin,
    IncidentTemplateToolsMixin,
    ProblemToolsMixin,
    ChangeToolsMixin,
    ChangeRequestMappingToolsMixin,
    KnowledgeToolsMixin,
    IncidentKnowledgeToolsMixin,
    IncidentAffectedCIToolsMixin,
    IncidentSLAToolsMixin,
    SLADefinitionToolsMixin,
    SLAMetricToolsMixin,
    NotificationAnalysisToolsMixin,
    NotificationToolsMixin,
):
    """The full ITSM toolkit (93 tools across 19 categories)."""


__all__ = ["ItsmTools", "ItsmToolsBase", "ItsmError"]
