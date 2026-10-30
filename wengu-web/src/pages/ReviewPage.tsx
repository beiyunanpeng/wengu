import {
  Alert,
  Badge,
  Button,
  Card,
  Divider,
  Group,
  Loader,
  Select,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useEffect, useState } from "react";

import { errorMessage } from "../api/client";
import {
  completeReview,
  getDueReviews,
  getQuizPaper,
  submitQuizPaper,
  submitReviewQuiz,
} from "../api/endpoints";
import type {
  CompleteReviewResponse,
  DueReviewItem,
  DueReviewResponse,
  PaperSubmitAnswer,
  PaperSubmitResponse,
  QuizPaperResponse,
  QuizQuestionView,
  ReviewTask,
} from "../api/types";
import ExplanationSlot from "../components/ExplanationSlot";
import MathText from "../components/MathText";
import QuizQuestionCard from "../components/QuizQuestionCard";
import QuizTopicPicker from "../components/QuizTopicPicker";

const TASK_LABELS: Record<ReviewTask, string> = {
  quiz: "同类题考核",
  self_eval: "纸上自评",
  redo: "原题重做",
};

const PAPER_STATUS: Record<
  PaperSubmitResponse["items"][number]["status"],
  { label: string; color: string }
> = {
  correct: { label: "答对", color: "green" },
  wrong: { label: "答错", color: "red" },
  uncertain: { label: "无法判定", color: "yellow" },
  skipped: { label: "已跳过", color: "gray" },
};

interface DueResult {
  scheduleId: number;
  mistakeId: number;
  completion: CompleteReviewResponse;
  verdict: "correct" | "wrong";
}

function taskInstruction(item: DueReviewItem): string {
  if (item.task === "quiz") {
    return "在页面内作答，提交后由服务端比对题库答案判分（前端拿不到答案）。";
  }
  if (item.task === "self_eval") {
    return "这道题无法在页面内键入（解答大题或依赖图形）：请在纸上完成，再对照卷面自评。";
  }
  return "该知识点题库暂无同类题（缺口）：请重做原题，再对照卷面自评。";
}

export default function ReviewPage() {
  const [due, setDue] = useState<DueReviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [results, setResults] = useState<DueResult[]>([]);

  const [topicId, setTopicId] = useState<string | null>(null);
  const [paperCount, setPaperCount] = useState("1");
  const [paper, setPaper] = useState<QuizPaperResponse | null>(null);
  const [paperAnswers, setPaperAnswers] = useState<
    Record<string, { answer: string; correct: boolean | null }>
  >({});
  const [paperBusy, setPaperBusy] = useState(false);
  const [paperError, setPaperError] = useState<string | null>(null);
  const [paperResult, setPaperResult] = useState<PaperSubmitResponse | null>(
    null,
  );

  async function load(showSpinner = true) {
    if (showSpinner) {
      setLoading(true);
    }
    try {
      setDue(await getDueReviews());
      setError(null);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  function removeDue(scheduleId: number) {
    setDue((previous) =>
      previous
        ? {
            ...previous,
            items: previous.items.filter(
              (entry) => entry.schedule_id !== scheduleId,
            ),
            total: Math.max(0, previous.total - 1),
          }
        : previous,
    );
    setAnswers((previous) => {
      const next = { ...previous };
      delete next[scheduleId];
      return next;
    });
  }

  async function finishQuiz(item: DueReviewItem) {
    if (!item.quiz || busyId !== null) {
      return;
    }
    if (item.task === "quiz" && !(answers[item.schedule_id] ?? "").trim()) {
      setActionError("请先作答再提交");
      return;
    }
    setBusyId(item.schedule_id);
    setActionError(null);
    try {
      const response = await submitReviewQuiz(item.mistake_id, {
        schedule_id: item.schedule_id,
        question_id: item.quiz.question_id,
        answer:
          item.task === "quiz" ? answers[item.schedule_id] ?? "" : undefined,
      });
      setResults((previous) => [
        {
          scheduleId: item.schedule_id,
          mistakeId: item.mistake_id,
          completion: response.completion,
          verdict: response.verdict,
        },
        ...previous,
      ]);
      removeDue(item.schedule_id);
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setBusyId(null);
    }
  }

  async function finishSelfEval(item: DueReviewItem, correct: boolean) {
    if (busyId !== null) {
      return;
    }
    setBusyId(item.schedule_id);
    setActionError(null);
    try {
      const completion =
        item.task === "self_eval" && item.quiz
          ? (
              await submitReviewQuiz(item.mistake_id, {
                schedule_id: item.schedule_id,
                question_id: item.quiz.question_id,
                correct,
              })
            ).completion
          : await completeReview(item.mistake_id, {
              schedule_id: item.schedule_id,
              correct,
            });
      setResults((previous) => [
        {
          scheduleId: item.schedule_id,
          mistakeId: item.mistake_id,
          completion,
          verdict: completion.correct ? "correct" : "wrong",
        },
        ...previous,
      ]);
      removeDue(item.schedule_id);
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setBusyId(null);
    }
  }

  async function drawPaper() {
    if (!topicId || paperBusy) {
      return;
    }
    setPaperBusy(true);
    setPaperError(null);
    try {
      const response = await getQuizPaper({
        topicId,
        count: Number(paperCount),
      });
      setPaper(response);
      setPaperAnswers({});
      setPaperResult(null);
    } catch (cause) {
      setPaperError(errorMessage(cause));
    } finally {
      setPaperBusy(false);
    }
  }

  function setPaperAnswer(questionId: string, answer: string) {
    setPaperAnswers((previous) => ({
      ...previous,
      [questionId]: {
        answer,
        correct: previous[questionId]?.correct ?? null,
      },
    }));
  }

  function setPaperVerdict(questionId: string, correct: boolean) {
    setPaperAnswers((previous) => ({
      ...previous,
      [questionId]: {
        answer: previous[questionId]?.answer ?? "",
        correct,
      },
    }));
  }

  async function submitPaper() {
    if (!paper || paperBusy) {
      return;
    }
    const answers: PaperSubmitAnswer[] = paper.items.map((question) => {
      const entry = paperAnswers[question.question_id];
      return {
        question_id: question.question_id,
        answer:
          question.mode === "system" && entry?.answer.trim()
            ? entry.answer.trim()
            : null,
        correct: question.mode === "self_eval" ? entry?.correct ?? null : null,
      };
    });
    if (
      !answers.some(
        (entry) => entry.answer !== null || entry.correct !== null,
      )
    ) {
      setPaperError("至少作答一题（或对解答大题自评）后再提交");
      return;
    }
    setPaperBusy(true);
    setPaperError(null);
    try {
      setPaperResult(
        await submitQuizPaper({
          topic_id: paper.topic_id,
          seed: paper.seed,
          count: paper.count,
          answers,
        }),
      );
    } catch (cause) {
      setPaperError(errorMessage(cause));
    } finally {
      setPaperBusy(false);
    }
  }

  function paperStatus(question: QuizQuestionView) {
    return paperResult?.items.find(
      (entry) => entry.question_id === question.question_id,
    );
  }

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center">
        <Title order={2}>复习与考核</Title>
        <Group gap="xs">
          {due && (
            <Text size="sm" c="dimmed">
              今天 {due.today} · 到期 {due.total} 道
            </Text>
          )}
          <Button size="compact-sm" variant="subtle" onClick={() => void load()}>
            刷新
          </Button>
        </Group>
      </Group>

      <Text size="sm" c="dimmed">
        到期任务：能按主考点取到同类题就考（服务端判分，计入掌握度）；
        解答大题或依赖图形则在纸上做、照卷面自评；题库缺口则重做原题。
        考核结果不新建错题本条目。
      </Text>

      {loading && (
        <Group justify="center" py="xl">
          <Loader />
        </Group>
      )}
      {error && (
        <Alert color="red" variant="light" title="加载失败">
          {error}
        </Alert>
      )}
      {actionError && (
        <Alert color="red" variant="light">
          {actionError}
        </Alert>
      )}

      {results.map((result) => (
        <Alert
          key={result.scheduleId}
          color={result.verdict === "correct" ? "green" : "orange"}
          variant="light"
          title={
            result.completion.graduated
              ? "答对了 · 这道题已毕业"
              : result.verdict === "correct"
                ? "答对了"
                : "这次没答对（排期不倒退）"
          }
        >
          <Stack gap={4}>
            {!result.completion.graduated && (
              <Text size="sm">
                下一次复习：{result.completion.due_on ?? "待定"}
                {result.completion.interval_days !== null
                  ? `（间隔 ${result.completion.interval_days} 天）`
                  : ""}
              </Text>
            )}
            <Text size="xs" c="dimmed">
              掌握度 {Math.round(result.completion.mastery * 100)}% · 等级{" "}
              {result.completion.state.rung + 1} · 连对{" "}
              {result.completion.state.trailing_correct} · 来源{" "}
              {result.completion.source === "system_quiz"
                ? "系统判分"
                : "学生自评"}
            </Text>
          </Stack>
        </Alert>
      ))}

      {!loading && !error && due && due.items.length === 0 && (
        <Alert color="blue" variant="light" title="今天没有到期复习">
          到期时间按实际完成日起算。可以去导入页转录新错题，或在下方手动组卷练习。
        </Alert>
      )}

      {due?.items.map((item) => (
        <Card key={item.schedule_id} withBorder>
          <Stack gap="sm">
            <Group justify="space-between" align="flex-start" wrap="wrap">
              <Group gap="xs" wrap="wrap">
                <Badge variant="light">复习 #{item.mistake_id}</Badge>
                <Badge
                  color={item.task === "quiz" ? "blue" : "grape"}
                  variant="light"
                >
                  {TASK_LABELS[item.task]}
                </Badge>
                {item.coverage === "gap" && (
                  <Badge color="gray" variant="light">
                    该知识点题库缺口
                  </Badge>
                )}
                {item.coverage_hint && (
                  <Badge color="yellow" variant="light">
                    {item.coverage_hint}
                  </Badge>
                )}
              </Group>
              <Text size="xs" c="dimmed">
                到期 {item.due_date} · 等级 {item.rung + 1} · 基础间隔{" "}
                {item.base_interval_days} 天
              </Text>
            </Group>

            <Text size="xs" c="dimmed">
              {taskInstruction(item)}
            </Text>

            {item.task === "redo" ? (
              <MathText text={item.problem_text || "（题目文本缺失）"} />
            ) : item.quiz ? (
              <QuizQuestionCard
                question={item.quiz}
                answer={answers[item.schedule_id] ?? ""}
                onAnswer={(value) =>
                  setAnswers((previous) => ({
                    ...previous,
                    [item.schedule_id]: value,
                  }))
                }
                disabled={busyId !== null}
              />
            ) : (
              <Alert color="orange" variant="light">
                取题失败：请刷新到期任务。
              </Alert>
            )}

            <Group>
              {item.task === "quiz" ? (
                <Button
                  onClick={() => void finishQuiz(item)}
                  loading={busyId === item.schedule_id}
                  disabled={busyId !== null}
                >
                  提交答案（服务端判分）
                </Button>
              ) : (
                <>
                  <Button
                    color="green"
                    onClick={() => void finishSelfEval(item, true)}
                    loading={busyId === item.schedule_id}
                    disabled={busyId !== null}
                  >
                    对照卷面：做对了
                  </Button>
                  <Button
                    color="red"
                    variant="light"
                    onClick={() => void finishSelfEval(item, false)}
                    loading={busyId === item.schedule_id}
                    disabled={busyId !== null}
                  >
                    没做对
                  </Button>
                </>
              )}
            </Group>

            <ExplanationSlot mistakeId={item.mistake_id} />
          </Stack>
        </Card>
      ))}

      <Divider my="sm" />

      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between" align="center" wrap="wrap">
            <Text fw={600}>手动组卷（选知识点 → 出 1..N 题）</Text>
            <Text size="xs" c="dimmed">
              结果计入该知识点掌握度，不新建错题
            </Text>
          </Group>
          <Group align="flex-end" wrap="wrap">
            <div style={{ flex: "1 1 320px", minWidth: 260 }}>
              <QuizTopicPicker value={topicId} onChange={setTopicId} />
            </div>
            <Select
              label="题量"
              data={["1", "2", "3", "4", "5"]}
              value={paperCount}
              onChange={(value) => setPaperCount(value ?? "1")}
              w={100}
            />
            <Button
              onClick={() => void drawPaper()}
              loading={paperBusy}
              disabled={!topicId}
            >
              抽题
            </Button>
          </Group>

          {paperError && (
            <Alert color="red" variant="light">
              {paperError}
            </Alert>
          )}

          {paper && (
            <Stack gap="sm">
              <Group gap="xs" wrap="wrap">
                <Text size="xs" c="dimmed">
                  知识点 {paper.topic_id} · seed {paper.seed} · 可答题{" "}
                  {paper.answerable_total}/{paper.pool_total}
                </Text>
                {paper.coverage === "thin" && (
                  <Badge color="yellow" variant="light">
                    该学科题库覆盖偏薄
                  </Badge>
                )}
                {paper.shortfall && (
                  <Badge color="orange" variant="light">
                    题库不足，只出 {paper.items.length} 题
                  </Badge>
                )}
              </Group>
              {paper.bank_gap || paper.items.length === 0 ? (
                <Alert color="gray" variant="light">
                  该知识点题库缺口，抽不出题；请改用错题原题重做。
                </Alert>
              ) : (
                <>
                  {paper.items.map((question, index) => {
                    const status = paperStatus(question);
                    const entry = paperAnswers[question.question_id];
                    return (
                      <Stack key={question.question_id} gap={6}>
                        <QuizQuestionCard
                          question={question}
                          index={index}
                          answer={entry?.answer ?? ""}
                          onAnswer={(value) =>
                            setPaperAnswer(question.question_id, value)
                          }
                          disabled={paperResult !== null}
                        />
                        {question.mode === "self_eval" && (
                          <Group gap="xs">
                            <Text size="xs" c="dimmed">
                              纸上完成，自评：
                            </Text>
                            <Button
                              size="compact-xs"
                              color="green"
                              variant={
                                entry?.correct === true ? "filled" : "light"
                              }
                              onClick={() =>
                                setPaperVerdict(question.question_id, true)
                              }
                              disabled={paperResult !== null}
                            >
                              做对了
                            </Button>
                            <Button
                              size="compact-xs"
                              color="red"
                              variant={
                                entry?.correct === false ? "filled" : "light"
                              }
                              onClick={() =>
                                setPaperVerdict(question.question_id, false)
                              }
                              disabled={paperResult !== null}
                            >
                              没做对
                            </Button>
                          </Group>
                        )}
                        {status && (
                          <Group gap={6}>
                            <Badge
                              color={PAPER_STATUS[status.status].color}
                              variant="light"
                            >
                              {PAPER_STATUS[status.status].label}
                            </Badge>
                            <Text size="xs" c="dimmed">
                              {status.replayed
                                ? "已提交过，按记录回放"
                                : status.mode === "system"
                                  ? "服务端判分"
                                  : "学生自评"}
                            </Text>
                          </Group>
                        )}
                      </Stack>
                    );
                  })}
                  {paperResult ? (
                    <Group>
                      <Badge color="green" variant="light">
                        答对 {paperResult.correct}
                      </Badge>
                      <Badge color="red" variant="light">
                        答错 {paperResult.wrong}
                      </Badge>
                      <Button
                        size="compact-sm"
                        variant="light"
                        onClick={() => void drawPaper()}
                        loading={paperBusy}
                      >
                        再抽一张
                      </Button>
                    </Group>
                  ) : (
                    <Group>
                      <Button
                        onClick={() => void submitPaper()}
                        loading={paperBusy}
                      >
                        提交本卷
                      </Button>
                      <Text size="xs" c="dimmed">
                        留空的题会跳过；提交后同 seed 重放同一张卷。
                      </Text>
                    </Group>
                  )}
                </>
              )}
            </Stack>
          )}
        </Stack>
      </Card>
    </Stack>
  );
}
