"""考核题面安全视图：只下发题干/选项/题型/题图与质量标签，绝不含答案。

P1-11 安全红线：判分全在服务端 `judgeAnswer` 完成，前端拿不到
`answer / accept / explanation / verify`，F12 偷看不到答案。
`unaudited / blind_verified / verify_status` 原样透传，家长能看到
"此题未经二遍复核"，绝不静默当已核验加分。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.seed.bank import BankQuestion

AnswerMode = Literal["system", "self_eval"]
VerifyStatus = Literal["verified", "unverifiable"]


class QuizChoiceView(BaseModel):
    key: str
    text: str
    figure: str | None = None


class QuizQuality(BaseModel):
    unaudited: bool
    blind_verified: bool
    verify_status: VerifyStatus
    verify_reason: str | None = None


class QuizQuestionView(BaseModel):
    question_id: str
    topic_id: str
    subject: str
    type: str
    difficulty: str | None = None
    prompt: str
    choices: list[QuizChoiceView]
    figure: str | None = None
    mode: AnswerMode
    seed: int
    pool_size: int
    quality: QuizQuality


def quiz_view(
    question: BankQuestion,
    *,
    mode: AnswerMode,
    seed: int,
    pool_size: int,
) -> QuizQuestionView:
    """题库题 → 可下发视图；`hide_choice_text` 的选项只给图不给被隐藏的文字。"""

    return QuizQuestionView(
        question_id=question.id,
        topic_id=question.topic_id,
        subject=question.subject,
        type=question.type,
        difficulty=question.difficulty,
        prompt=question.prompt,
        choices=[
            QuizChoiceView(
                key=choice.key,
                text="" if question.hide_choice_text else choice.text,
                figure=choice.figure,
            )
            for choice in question.choices
        ],
        figure=question.figure,
        mode=mode,
        seed=seed,
        pool_size=pool_size,
        quality=QuizQuality(
            unaudited=question.unaudited,
            blind_verified=question.blind_verified,
            verify_status=question.verify_status,
            verify_reason=question.verify_reason,
        ),
    )
