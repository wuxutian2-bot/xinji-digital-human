"""E3c experimental interpretation of unknown intent, separate from production."""

import copy
import json

from decision_contract import CONTRACT, transform as old_transform

VARIANTS = ("contract_v1", "contract_v2")
OLD_HELP = "4. 用户明确想要办法、小步骤或建议，primary=seeking_practical_help且advice_preference=requested：collaborative_problem_solving + offer_small_step。即使略有紧张，也应回应实际求助。"
NEW_HELP = """4. 判断当前用户是否正在向你请求行动上的帮助：询问你应当怎样做、先做哪件事、哪种安排比较合适、请你协助选择或规划，都是实际求助；不必出现‘建议’‘步骤’等词。只要当前原文确有这样的请求且没有拒绝建议，就选择collaborative_problem_solving + offer_small_step。interaction_intent.primary=unknown或advice_preference=unspecified只说明本机规则没识别出来，不是否定求助，也不是选择倾听的理由。即使略有紧张，也应回应实际求助。
区分求助与相似表达：仅描述自己的打算或已经做过的事、转述他人的疑问、抱怨式反问，不等于向你请求行动建议。不要因问号、‘怎么办’等单个词就判定同意建议；看谁在问、是否问你、是否要你协助做事。用户只是表达感受时倾听，无法确定时用reflect_and_clarify + explore_context，不擅自提供步骤。明确的拒绝建议或只想倾诉仍由第3条优先处理。"""
if OLD_HELP not in CONTRACT:
    raise ValueError("Frozen v1 contract changed")
CONTRACT_V2 = CONTRACT.replace(OLD_HELP, NEW_HELP)


def transform(request, variant):
    if variant not in VARIANTS:
        raise ValueError("Unsupported intent contract")
    # Input is always a recorded v1 request, including its existing protections.
    result = copy.deepcopy(request)
    schema = result["response_format"]["schema"]
    expected = CONTRACT + json.dumps(schema, ensure_ascii=False)
    if result["messages"][0]["content"] != expected:
        raise ValueError("Expected frozen v1 request")
    if variant == "contract_v2":
        result["messages"][0]["content"] = CONTRACT_V2 + json.dumps(
            schema, ensure_ascii=False
        )
    return result


def from_baseline(request, variant):
    return transform(old_transform(request, "contract_v1"), variant)
