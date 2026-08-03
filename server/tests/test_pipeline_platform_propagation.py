"""Pipeline 生文节点的可选目标平台契约。"""

from types import SimpleNamespace

import pytest

from server.app.modules.pipelines.nodes.base import NodeRunContext
from server.app.shared.errors import ValidationError


class _Session:
    def close(self) -> None:
        pass


class _CaptureRng:
    def __init__(self) -> None:
        self.candidates = []

    def choice(self, candidates):
        self.candidates = list(candidates)
        return self.candidates[0]


def test_runtime_template_selection_keeps_generic_or_matching_platform(monkeypatch):
    from server.app.modules.ai_generation import runtime_templates

    templates = {
        1: SimpleNamespace(id=1, platform="xiaohongshu", is_enabled=True),
        2: SimpleNamespace(id=2, platform=None, is_enabled=True),
        3: SimpleNamespace(id=3, platform="toutiao", is_enabled=True),
        4: SimpleNamespace(id=4, platform="toutiao", is_enabled=False),
    }
    calls: list[tuple[int, str | None]] = []

    def _get_runtime_template(_db, template_id, *, user_id, scope, platform=None):
        assert user_id == 7
        assert scope == "generation"
        calls.append((template_id, platform))
        template = templates[template_id]
        if platform is not None and template.platform not in (None, platform):
            return None
        return template

    monkeypatch.setattr(
        runtime_templates,
        "get_runtime_prompt_template",
        _get_runtime_template,
    )
    rng = _CaptureRng()

    selected = runtime_templates.pick_valid_template(
        _Session(),
        [1, 2, 3, 4, 2],
        7,
        target_platform_code="toutiao",
        rng=rng,
    )

    assert selected.id == 2
    assert [template.id for template in rng.candidates] == [2, 3]
    assert calls == [(1, "toutiao"), (2, "toutiao"), (3, "toutiao"), (4, "toutiao")]


def test_runtime_template_selection_rejects_unknown_platform_before_lookup(monkeypatch):
    from server.app.modules.ai_generation import runtime_templates

    lookup_called = False

    def _unexpected_lookup(*_args, **_kwargs):
        nonlocal lookup_called
        lookup_called = True

    monkeypatch.setattr(
        runtime_templates,
        "get_runtime_prompt_template",
        _unexpected_lookup,
    )

    with pytest.raises(ValidationError, match="Unsupported content platform code"):
        runtime_templates.pick_valid_template(
            _Session(),
            [1],
            7,
            target_platform_code="unknown",
        )
    assert lookup_called is False


@pytest.mark.parametrize(
    ("module_name", "handler_name", "config"),
    [
        (
            "server.app.modules.pipelines.nodes.ai_generate_node",
            "run_ai_generate",
            {"prompt_template_id": 11, "count": 1, "model": None},
        ),
        (
            "server.app.modules.pipelines.nodes.ai_compose",
            "run_ai_compose",
            {"prompt_template_ids": [11], "count": 1, "ai_engine": None},
        ),
    ],
)
@pytest.mark.parametrize("target_platform_code", [None, "toutiao"])
def test_generation_nodes_propagate_optional_platform(
    monkeypatch,
    module_name,
    handler_name,
    config,
    target_platform_code,
):
    import importlib

    module = importlib.import_module(module_name)
    captured: dict[str, object] = {}

    def _pick_template(
        _db,
        template_ids,
        user_id,
        *,
        target_platform_code=None,
        **_kwargs,
    ):
        captured["template_ids"] = list(template_ids)
        captured["template_platform"] = target_platform_code
        assert user_id == 7
        return SimpleNamespace(
            id=11,
            name="模板",
            content="写：{{问题}}",
            scope="generation",
            platform=target_platform_code,
            is_enabled=True,
            is_deleted=False,
            updated_at=None,
        )

    def _generate_article(**kwargs):
        captured["writer_platform"] = kwargs.get("target_platform_code")
        captured["source_template_fingerprint"] = kwargs.get("source_template_fingerprint")
        return 101

    monkeypatch.setattr(module, "pick_valid_template", _pick_template)
    monkeypatch.setattr(module, "generate_article_from_prompt", _generate_article)
    monkeypatch.setattr(
        "server.app.core.config.get_settings",
        lambda: SimpleNamespace(ai_generate_max_count=10),
    )
    node_config = {**config}
    if target_platform_code is not None:
        node_config["target_platform_code"] = target_platform_code

    result = getattr(module, handler_name)(
        NodeRunContext(
            session_factory=_Session,
            user_id=7,
            config=node_config,
            inputs={"question_text": "1. 测试问题"},
            upstream={},
            pipeline_name="测试工作流",
        )
    )

    assert result.article_ids == [101]
    assert captured["template_platform"] == target_platform_code
    assert captured["writer_platform"] == target_platform_code
    assert len(captured["source_template_fingerprint"]) == 64


@pytest.mark.parametrize(
    ("module_name", "handler_name", "config", "raises_directly"),
    [
        (
            "server.app.modules.pipelines.nodes.ai_generate_node",
            "run_ai_generate",
            {
                "prompt_template_id": 11,
                "count": 1,
                "model": None,
                "target_platform_code": "toutiao",
            },
            True,
        ),
        (
            "server.app.modules.pipelines.nodes.ai_compose",
            "run_ai_compose",
            {
                "prompt_template_ids": [11],
                "count": 1,
                "ai_engine": None,
                "target_platform_code": "toutiao",
            },
            False,
        ),
    ],
)
def test_generation_nodes_do_not_write_when_no_platform_compatible_template(
    monkeypatch,
    module_name,
    handler_name,
    config,
    raises_directly,
):
    import importlib

    module = importlib.import_module(module_name)
    writer_called = False

    def _no_compatible_template(
        _db,
        _template_ids,
        _user_id,
        *,
        target_platform_code=None,
        **_kwargs,
    ):
        assert target_platform_code == "toutiao"
        return None

    def _unexpected_writer(**_kwargs):
        nonlocal writer_called
        writer_called = True
        return 101

    monkeypatch.setattr(module, "pick_valid_template", _no_compatible_template)
    monkeypatch.setattr(module, "generate_article_from_prompt", _unexpected_writer)
    monkeypatch.setattr(
        "server.app.core.config.get_settings",
        lambda: SimpleNamespace(ai_generate_max_count=10),
    )
    ctx = NodeRunContext(
        session_factory=_Session,
        user_id=7,
        config=config,
        inputs={"question_text": "1. 测试问题"},
        upstream={},
    )

    if raises_directly:
        with pytest.raises(ValidationError, match="目标平台不兼容"):
            getattr(module, handler_name)(ctx)
    else:
        result = getattr(module, handler_name)(ctx)
        assert result.article_ids == []
        assert len(result.output["errors"]) == 1
        assert "目标平台不兼容" in result.output["errors"][0]
    assert writer_called is False


def test_pipeline_node_type_api_exposes_optional_target_platform():
    from server.app.modules.pipelines.router import get_node_types

    node_types = {item["type"]: item for item in get_node_types()["node_types"]}

    for node_type in ("ai_generate", "ai_compose"):
        fields = {field["key"]: field for field in node_types[node_type]["config_schema"]}
        field = fields["target_platform_code"]
        assert field["type"] == "text"
        assert "可选" in field["label"]
        assert "留空保持旧工作流" in field["hint"]
