"""OpenAI-compat 视觉适配器 + 路由注册表（MockTransport，零网络、零密钥）。"""

from __future__ import annotations

import json

import httpx
import pytest
from app.core.config import RuntimeConfig
from app.providers.base import ExtractedProblem
from app.providers.doubao import DoubaoVisionProvider
from app.providers.http import ProviderResponseError
from app.providers.openai_vision import OpenAIVisionProvider
from app.providers.qwen_vl import QwenVLProvider
from app.providers.registry import (
    ProviderConfigError,
    create_text_provider,
    create_vision_provider,
    resolve_task_model,
    resolve_task_providers,
)
from app.providers.tencent import TencentVisionProvider


def _runtime(**overrides) -> RuntimeConfig:
    base = dict(
        model_tier_default="value",
        daily_call_budget_cny=10.0,
        daily_call_limit=200,
        variant_on_demand=True,
        provider_routing={},
        model_prices={},
    )
    base.update(overrides)
    return RuntimeConfig(**base)


def _settings(**env: str | None):
    from app.core.config import Settings

    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        doubao_api_key=env.get("doubao_api_key"),
        doubao_model_value=env.get("doubao_model_value"),
        doubao_model_flagship=env.get("doubao_model_flagship"),
        qwen_api_key=env.get("qwen_api_key"),
        qwen_model_value=env.get("qwen_model_value"),
        qwen_model_flagship=env.get("qwen_model_flagship"),
        deepseek_api_key=env.get("deepseek_api_key"),
        deepseek_model=env.get("deepseek_model", "deepseek-chat"),
    )


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://example.com")


@pytest.mark.unit
async def test_extract_problem_parses_json_embedded_in_prose(tmp_path) -> None:
    image = tmp_path / "x.png"
    image.write_bytes(b"\x89PNGfake")

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        content = body["messages"][0]["content"]
        image_parts = [part for part in content if part["type"] == "image_url"]
        assert image_parts and image_parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '说明文字\n{"problem_text": "1+1=", "student_answer": "2", "confidence": 0.93}\n完'}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            },
        )

    provider = OpenAIVisionProvider(api_key="k", model="m", client=_client(handler))
    result, meta = await provider.extract_problem(str(image), prompt="p")
    assert result == ExtractedProblem(
        problem_text="1+1=",
        student_answer="2",
        confidence=0.93,
        needs_human_review=True,
        raw={"problem_text": "1+1=", "student_answer": "2", "confidence": 0.93},
    )
    assert meta.provider == "openai_vision"
    assert meta.model == "m"
    assert meta.usage.input_tokens == 100


def _extract_handler(payload: dict[str, object]):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]},
        )

    return handler


@pytest.mark.unit
async def test_extract_problem_parses_completeness_and_rejects_percentage_confidence(
    tmp_path,
) -> None:
    image = tmp_path / "x.png"
    image.write_bytes(b"\x89PNGfake")
    provider = OpenAIVisionProvider(
        api_key="k",
        model="m",
        client=_client(
            _extract_handler(
                {
                    "problem_text": "1+1=",
                    "student_answer": "2",
                    "problem_complete": "false",
                    "confidence": 93,
                }
            )
        ),
    )

    result, _ = await provider.extract_problem(str(image), prompt="p")

    assert result.problem_complete is False
    assert result.confidence is None  # 93 不是 0–1，不制造虚假精确


@pytest.mark.unit
async def test_extract_problem_rescues_string_list_and_numeric_answer(tmp_path) -> None:
    image = tmp_path / "x.png"
    image.write_bytes(b"\x89PNGfake")
    provider = OpenAIVisionProvider(
        api_key="k",
        model="m",
        client=_client(
            _extract_handler(
                {
                    "problem_text": ["第一行", "第二行"],
                    "student_answer": 2,
                    "problem_complete": True,
                    "confidence": 0.7,
                }
            )
        ),
    )

    result, _ = await provider.extract_problem(str(image), prompt="p")

    assert result.problem_text == "第一行\n第二行"
    assert result.student_answer == "2"
    assert result.problem_complete is True
    assert result.confidence == 0.7


@pytest.mark.unit
async def test_extract_problem_rejects_structured_problem_text(tmp_path) -> None:
    image = tmp_path / "x.png"
    image.write_bytes(b"\x89PNGfake")
    provider = OpenAIVisionProvider(
        api_key="k",
        model="m",
        client=_client(
            _extract_handler({"problem_text": {"bad": 1}, "student_answer": "2"})
        ),
    )

    with pytest.raises(ProviderResponseError, match="problem_text"):
        await provider.extract_problem(str(image), prompt="p")


@pytest.mark.unit
async def test_extract_problem_rejects_structured_answer(tmp_path) -> None:
    image = tmp_path / "x.png"
    image.write_bytes(b"\x89PNGfake")
    provider = OpenAIVisionProvider(
        api_key="k",
        model="m",
        client=_client(
            _extract_handler({"problem_text": "1+1=", "student_answer": {"bad": 1}})
        ),
    )

    with pytest.raises(ProviderResponseError, match="student_answer"):
        await provider.extract_problem(str(image), prompt="p")


@pytest.mark.unit
async def test_grade_falls_back_to_uncertain_on_unknown_verdict() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"verdict": "mostly-correct", "rationale": "?"}'}}],
                "usage": {},
            },
        )

    provider = OpenAIVisionProvider(api_key="k", model="m", client=_client(handler))
    result, _ = await provider.grade("题", "答", prompt="p")
    assert result.verdict == "uncertain"
    assert result.source == "ai"


@pytest.mark.unit
async def test_solve_explain_falls_back_to_raw_text_when_no_steps() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "整体讲解文字"}}]})

    provider = OpenAIVisionProvider(api_key="k", model="m", client=_client(handler))
    result, _ = await provider.solve_explain("题", prompt="p", hint_level=9)
    assert result.steps == ("整体讲解文字",)
    assert result.focus == ""
    assert result.consolidation == ""
    assert result.hint_level == 3  # 档位由 adapter 夹紧，不信任模型回传


@pytest.mark.unit
async def test_solve_explain_parses_focus_and_consolidation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"focus": "先看问什么", "steps": ["第一步", "第二步"], '
                                '"consolidation": "自己复述一遍", "answer": "42"}'
                            )
                        }
                    }
                ]
            },
        )

    provider = OpenAIVisionProvider(api_key="k", model="m", client=_client(handler))
    result, _ = await provider.solve_explain("题", prompt="p", hint_level=1)
    assert result.focus == "先看问什么"
    assert result.steps == ("第一步", "第二步")
    assert result.consolidation == "自己复述一遍"
    assert result.answer == "42"
    assert result.hint_level == 1


@pytest.mark.unit
def test_vendor_defaults_and_constructor_validation() -> None:
    assert DoubaoVisionProvider(api_key="k", model="m").default_base_url.endswith("volces.com/api/v3")
    assert QwenVLProvider(api_key="k", model="m").default_base_url.endswith(
        "dashscope.aliyuncs.com/compatible-mode/v1"
    )
    with pytest.raises(ValueError):
        OpenAIVisionProvider(api_key="", model="m")
    with pytest.raises(ValueError):
        OpenAIVisionProvider(api_key="k", model=" ")


@pytest.mark.unit
async def test_qwen_provider_disables_thinking(tmp_path) -> None:
    image = tmp_path / "x.png"
    image.write_bytes(b"\x89PNGfake")
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"problem_text": "1+1=", "student_answer": "2"}'
                        }
                    }
                ]
            },
        )

    provider = QwenVLProvider(api_key="k", model="m", client=_client(handler))
    await provider.extract_problem(str(image), prompt="p")

    assert seen["enable_thinking"] is False


@pytest.mark.unit
async def test_tencent_stub_raises_not_implemented() -> None:
    provider = TencentVisionProvider()
    with pytest.raises(NotImplementedError, match="stub"):
        await provider.extract_problem("x.png", prompt="p")


@pytest.mark.unit
def test_routing_defaults_and_hot_override() -> None:
    assert resolve_task_providers("extract_problem", _runtime()) == ("doubao", "qwen_vl")
    assert resolve_task_providers("dictation_extract", _runtime()) == ("qwen_vl", "doubao")
    runtime = _runtime(
        provider_routing={"grade": "qwen_vl", "text": ["mock", "mock_text"]}
    )
    assert resolve_task_providers("grade", runtime) == ("qwen_vl",)
    assert resolve_task_providers("text", runtime) == ("mock", "mock_text")

    with pytest.raises(ProviderConfigError):
        resolve_task_providers("no_such_task", _runtime())


@pytest.mark.unit
def test_routing_dedupes_and_rejects_empty() -> None:
    runtime = _runtime(
        provider_routing={
            "extract_problem": ["doubao", " qwen_vl ", "doubao"],
            "grade": [],
        }
    )
    assert resolve_task_providers("extract_problem", runtime) == ("doubao", "qwen_vl")
    with pytest.raises(ProviderConfigError, match="路由为空"):
        resolve_task_providers("grade", runtime)


@pytest.mark.unit
def test_task_model_defaults_are_vlm_for_extract_and_ocr_for_dictation() -> None:
    settings = _settings(
        qwen_api_key="k",
        qwen_model_value="qwen3.5-ocr",
        qwen_model_flagship="qwen3.8-max",
    )
    assert resolve_task_model("extract_problem", "qwen_vl", _runtime(), settings) == "qwen3.8-max"
    assert resolve_task_model("grade", "qwen_vl", _runtime(), settings) == "qwen3.8-max"
    assert (
        resolve_task_model("solve_explain", "qwen_vl", _runtime(), settings) == "qwen3.8-max"
    )
    assert (
        resolve_task_model("dictation_extract", "qwen_vl", _runtime(), settings) == "qwen3.5-ocr"
    )
    # 未列入默认表的 provider/task 沿用档位默认
    assert resolve_task_model("extract_problem", "doubao", _runtime(), settings) is None
    assert resolve_task_model("text", "deepseek", _runtime(), settings) is None


@pytest.mark.unit
def test_task_model_explicit_override_wins_and_empty_fails_fast() -> None:
    settings = _settings(
        qwen_api_key="k",
        qwen_model_value="qwen3.5-ocr",
        qwen_model_flagship="qwen3.8-max",
    )
    runtime = _runtime(task_models={"extract_problem": {"qwen_vl": "qwen3.8-max-2026"}})
    assert (
        resolve_task_model("extract_problem", "qwen_vl", runtime, settings) == "qwen3.8-max-2026"
    )
    # 覆盖只作用于指定 task
    assert (
        resolve_task_model("dictation_extract", "qwen_vl", runtime, settings) == "qwen3.5-ocr"
    )

    empty = _runtime(task_models={"extract_problem": {"qwen_vl": "  "}})
    with pytest.raises(ProviderConfigError, match="task_models.extract_problem.qwen_vl"):
        resolve_task_model("extract_problem", "qwen_vl", empty, settings)


@pytest.mark.unit
def test_task_model_missing_default_slot_fails_fast() -> None:
    settings = _settings(qwen_api_key="k", qwen_model_value="qwen3.5-ocr")
    with pytest.raises(ProviderConfigError, match="WENGU_QWEN_MODEL_FLAGSHIP"):
        resolve_task_model("extract_problem", "qwen_vl", _runtime(), settings)


@pytest.mark.unit
def test_explicit_model_passed_to_vision_and_text_factories() -> None:
    settings = _settings(
        qwen_api_key="k",
        qwen_model_value="qwen3.5-ocr",
        qwen_model_flagship="qwen3.8-max",
        deepseek_api_key="k",
    )
    provider = create_vision_provider(
        "qwen_vl", settings=settings, runtime=_runtime(), model="qwen3.8-max-2026"
    )
    assert provider.model == "qwen3.8-max-2026"
    with pytest.raises(ProviderConfigError, match="task_models 指定的模型"):
        create_vision_provider("qwen_vl", settings=settings, runtime=_runtime(), model=" ")

    text = create_text_provider("deepseek", settings=settings, model="deepseek-reasoner")
    assert text.model == "deepseek-reasoner"
    assert create_text_provider("deepseek", settings=settings).model == "deepseek-chat"


@pytest.mark.unit
def test_registry_fails_fast_on_missing_config() -> None:
    runtime = _runtime()
    with pytest.raises(ProviderConfigError, match="WENGU_DOUBAO_API_KEY"):
        create_vision_provider("doubao", settings=_settings(), runtime=runtime)

    settings = _settings(doubao_api_key="k")  # 缺模型名
    with pytest.raises(ProviderConfigError, match="WENGU_DOUBAO_MODEL_VALUE"):
        create_vision_provider("doubao", settings=settings, runtime=runtime)

    settings = _settings(
        doubao_api_key="k", doubao_model_value="lite-x", doubao_model_flagship="pro-x"
    )
    provider = create_vision_provider("doubao", settings=settings, runtime=runtime)
    assert provider.model == "lite-x"
    flagship = create_vision_provider(
        "doubao", settings=settings, runtime=_runtime(model_tier_default="flagship")
    )
    assert flagship.model == "pro-x"

    mock = create_vision_provider("mock", settings=settings, runtime=runtime)
    assert mock.name == "mock"


@pytest.mark.unit
def test_registry_rejects_unknown_provider() -> None:
    with pytest.raises(ProviderConfigError, match="未知视觉供应商"):
        create_vision_provider("openai", settings=_settings(), runtime=_runtime())
