"""Single source for the mainland-China crisis resource card.

Human number verification: 2026-11-13 / 人工核实, reported by the user.
Official sources supplied in that verification record:
- 全国统一心理援助热线: 国家卫生健康委.
- 希望24热线: 希望24热线官网.
- 急救: 国家卫健委《院前医疗急救管理办法》.
- 报警: 公安部.
Service hours and source URLs were not supplied. Do not assume 24/7
availability from a service's name. See docs/mental_health_crisis_support.md.
"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CrisisResource:
    name: str
    number: str
    description: str
    available: str = "接听时段以服务方公布为准"


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
