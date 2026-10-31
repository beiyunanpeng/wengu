import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { errorMessage } from "../api/client";
import { getPaperAnswers, getQuizPaper } from "../api/endpoints";
import type {
  PaperAnswerKeyResponse,
  QuizPaperResponse,
  QuizQuestionView,
} from "../api/types";
import MathText from "../components/MathText";
import { QuestionFigure } from "../components/QuizQuestionCard";
import { toISODate } from "../lib/dates";
import "../print.css";

const MAX_COUNT = 20;
const MAX_SEED = 0xffffffff;

const TYPE_LABELS: Record<string, string> = {
  choice: "选择",
  numeric: "数值",
  short: "短答",
  self: "解答",
};

function questionDetail(question: QuizQuestionView): string {
  const parts = [
    TYPE_LABELS[question.type] ?? question.type,
    question.mode === "self_eval" ? "纸上作答" : "页面作答",
  ];
  if (question.quality.unaudited) {
    parts.push("题库未经审核");
  }
  if (!question.quality.blind_verified) {
    parts.push("未经二遍复核");
  }
  return parts.join(" · ");
}

export default function PrintPaperPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const topicId = params.get("topic_id");
  const countValue = Number(params.get("count") ?? "3");
  const count =
    Number.isInteger(countValue) && countValue >= 1 && countValue <= MAX_COUNT
      ? countValue
      : 3;
  const seedValue = Number(params.get("seed"));
  const seed =
    params.get("seed") &&
    Number.isInteger(seedValue) &&
    seedValue >= 0 &&
    seedValue <= MAX_SEED
      ? seedValue
      : undefined;

  const [paper, setPaper] = useState<QuizPaperResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [answers, setAnswers] = useState<PaperAnswerKeyResponse | null>(null);
  const [showAnswers, setShowAnswers] = useState(false);
  const [answerBusy, setAnswerBusy] = useState(false);
  const [answerError, setAnswerError] = useState<string | null>(null);

  useEffect(() => {
    if (!topicId) {
      setLoading(false);
      setError("缺少 topic_id，请从「复习考核」组卷后再导出练习卷。");
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    getQuizPaper({ topicId, count, seed })
      .then((response) => {
        if (!active) {
          return;
        }
        setPaper(response);
        if (seed === undefined) {
          const next = new URLSearchParams(window.location.search);
          next.set("seed", String(response.seed));
          window.history.replaceState(
            null,
            "",
            `${window.location.pathname}?${next.toString()}`,
          );
        }
      })
      .catch((cause: unknown) => {
        if (active) {
          setError(errorMessage(cause));
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [topicId, count, seed]);

  async function toggleAnswers() {
    if (showAnswers) {
      setShowAnswers(false);
      return;
    }
    if (!paper || answerBusy) {
      return;
    }
    if (
      answers &&
      answers.topic_id === paper.topic_id &&
      answers.seed === paper.seed &&
      answers.count === paper.count
    ) {
      setShowAnswers(true);
      return;
    }
    setAnswerBusy(true);
    setAnswerError(null);
    try {
      const response = await getPaperAnswers({
        topicId: paper.topic_id,
        count: paper.count,
        seed: paper.seed,
      });
      setAnswers(response);
      setShowAnswers(true);
    } catch (cause) {
      setAnswerError(errorMessage(cause));
    } finally {
      setAnswerBusy(false);
    }
  }

  const today = toISODate(new Date());
  const printable = Boolean(paper && paper.items.length > 0);

  return (
    <div className="print-shell" data-print-paper="true">
      <div className="print-toolbar">
        <div className="print-toolbar-title">
          <strong>同类题练习卷</strong>
          <span>
            {topicId ?? "缺少知识点"}
            {paper ? ` · ${paper.items.length} 题 · seed ${paper.seed}` : ""}
          </span>
        </div>
        <div className="print-actions">
          <button
            type="button"
            className="primary"
            onClick={() => window.print()}
            disabled={loading || !printable}
          >
            打印 / 另存为 PDF
          </button>
          <button
            type="button"
            onClick={() => void toggleAnswers()}
            disabled={!printable || answerBusy}
          >
            {answerBusy
              ? "正在读取答案…"
              : showAnswers
                ? "隐藏家长答案页"
                : "显示家长答案页（需家长解锁）"}
          </button>
          <button type="button" onClick={() => navigate("/review")}>
            返回组卷
          </button>
        </div>
      </div>

      <main className="print-sheet">
        <header className="print-doc-head">
          <div>
            <h1 className="print-doc-title">同类题练习卷</h1>
            <div className="print-meta">
              知识点：{paper?.topic_id ?? topicId ?? "未知"}
              {paper ? ` · 共 ${paper.items.length} 题 · seed ${paper.seed}` : ""}
            </div>
          </div>
          <div className="print-meta">打印日期 {today}</div>
        </header>

        {loading && <div className="print-empty">正在抽题…</div>}
        {error && (
          <div className="print-error" role="alert">
            <div>读取失败：{error}</div>
            <div className="print-note">
              组卷属于家长区，请先在「复习考核」页解锁家长区后再试。
            </div>
          </div>
        )}

        {!loading && !error && paper && paper.items.length === 0 && (
          <div className="print-empty">
            该知识点题库缺口，没有可打印的题目；可改用错题原题重做。
          </div>
        )}

        {!loading &&
          !error &&
          paper?.items.map((question, index) => (
            <article
              className="print-question"
              key={question.question_id}
              data-paper-question={question.question_id}
            >
              <header className="print-question-head">
                <span>第 {index + 1} 题</span>
                <span>{questionDetail(question)}</span>
              </header>
              <div className="print-prompt">
                <MathText text={question.prompt} />
              </div>
              {question.figure && <QuestionFigure svg={question.figure} />}
              {question.choices.length > 0 && (
                <ol className="print-choices">
                  {question.choices.map((choice) => (
                    <li key={choice.key}>
                      <span className="print-choice-key">{choice.key}.</span>
                      <span>
                        {choice.text && <MathText text={choice.text} />}
                        {choice.figure && <QuestionFigure svg={choice.figure} />}
                      </span>
                    </li>
                  ))}
                </ol>
              )}
              {question.mode === "self_eval" && (
                <p className="print-note">
                  本题为解答题或依赖图形题：请在纸上完成，无需在页面作答。
                </p>
              )}
            </article>
          ))}

        {paper && paper.items.length > 0 && (
          <p className="print-note">
            本卷只含题干与选项，不含答案；答案页由家长单独选择是否打印。
          </p>
        )}

        {showAnswers && answers && (
          <section className="print-answer-page" data-answer-page="true">
            <h2>家长答案页</h2>
            <p className="print-note">
              孩子作答时请勿打印本页；答案页从卷末单独分页。
            </p>
            <ol className="print-answer-list">
              {answers.items.map((key, index) => (
                <li key={key.question_id}>
                  <div>
                    第 {index + 1} 题
                    {key.mode === "self_eval" ? "（解答题参考正答）" : ""}
                  </div>
                  <div>
                    正答：<MathText text={key.answer} />
                  </div>
                  {key.acceptable_answers.length > 0 && (
                    <div>
                      可接受：
                      <MathText text={key.acceptable_answers.join(" / ")} />
                    </div>
                  )}
                </li>
              ))}
            </ol>
          </section>
        )}

        {answerError && (
          <div className="print-error" role="alert">
            答案页读取失败：{answerError}
            <div className="print-note">
              答案页属于家长区，请先在「复习考核」页解锁家长区。
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
