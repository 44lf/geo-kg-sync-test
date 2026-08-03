"""共享的运行期 generation 提示词模板选择。"""

import random

from sqlalchemy.orm import Session

from server.app.modules.content_platforms import validate_content_platform_code
from server.app.modules.prompt_templates.models import PromptTemplate
from server.app.modules.prompt_templates.service import get_runtime_prompt_template


def pick_valid_template(
    db: Session,
    template_ids: list[int],
    user_id: int,
    *,
    target_platform_code: str | None = None,
    rng: random.Random | None = None,
) -> PromptTemplate | None:
    """从可用且平台兼容的 generation 模板中随机选择一个。

    ``target_platform_code`` 缺省时不增加平台过滤，保留存量 Pipeline 的通用行为；
    一旦配置，只允许目标平台专属或 ``platform IS NULL`` 的通用模板。
    """
    target_platform_code = validate_content_platform_code(target_platform_code or None)
    candidates: list[PromptTemplate] = []
    for template_id in dict.fromkeys(template_ids):
        template = get_runtime_prompt_template(
            db,
            template_id,
            user_id=user_id,
            scope="generation",
            platform=target_platform_code,
        )
        if template is not None and template.is_enabled:
            candidates.append(template)
    if not candidates:
        return None
    return (rng or random.Random()).choice(candidates)
