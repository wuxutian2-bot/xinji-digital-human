"""Single source for the mainland-China crisis resource card.

Candidate numbers come from docs/plans/2026-11-13-交接执行手册.md (2026-11-13).
Human verification date: pending. Official source: pending human verification
against the National Health Commission / each service operator before release.
Do not interpret the implementation date as a verification date or assume 24/7
availability from a service's name. See docs/mental_health_crisis_support.md.
"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CrisisResource:
    name: str
    number: str
    description: str
    available: str = "服务时间待人工核实"


PSYCHOLOGICAL_SUPPORT = CrisisResource(
    "全国统一心理援助热线", "12356", "心理援助与支持"
)
EMERGENCY_MEDICAL = CrisisResource("急救", "120", "已经受伤或有紧急医疗需要")
EMERGENCY_POLICE = CrisisResource("报警", "110", "面临即时人身危险")
CRISIS_RESOURCES = (
    PSYCHOLOGICAL_SUPPORT,
    CrisisResource("希望24热线", "400-161-9995", "心理危机支持"),
    EMERGENCY_MEDICAL,
    EMERGENCY_POLICE,
)


def crisis_resources_payload() -> list[dict[str, str]]:
    """Return independent dictionaries so per-turn actions cannot mutate the list."""
    return [asdict(resource) for resource in CRISIS_RESOURCES]


CRISIS_CONTACT_TEXT = (
    f"在中国大陆，紧急危险时请立即拨打急救 {EMERGENCY_MEDICAL.number} "
    f"或报警 {EMERGENCY_POLICE.number}；心理援助可拨打 "
    f"{PSYCHOLOGICAL_SUPPORT.number}。其他地区请联系当地急救服务。"
)
