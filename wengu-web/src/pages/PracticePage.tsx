import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { errorMessage } from "../api/client";
import { startPractice, submitPractice } from "../api/endpoints";
import type {
  PracticeStartResponse,
  PracticeSubmitResponse,
  QuizQuestionView,
} from "../api/types";
import QuizQuestionCard from "../components/QuizQuestionCard";

const STATUS_LABELS: Record<
  PracticeSubmitResponse["items"][number]["status"],
  { label: string; color: string }
> = {
  correct: { label: "答对", color: "green" },
  wrong: { label: "答错", color: "red" },
  uncertain: { label: "无法判定", color: "yellow" },
  skipped: { label: "已跳过", color: "gray" },
};

export default function PracticePage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const mistakeId = params.get("mistake_id")
    ? Number(params.get("mistake_id"))
    : undefined;
  const topicId = params.get("topic_id") ?? undefined;
  const requestedCount = Number(params.get("count") ?? "3");
  const count = Number.isFinite(requestedCount) ? requestedCount : 3;

  const [paper, setPaper] = useState<PracticeStartResponse | null>(null);
  const [drafts, setDrafts] = useState<
    Record<string, { answer: string; correct: boolean | null }>
  >({});
  const [result, setResult] = useState<PracticeSubmitResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (mistakeId === undefined && !topicId) {
      setLoading(false);
      setError("缺少练习来源：请从错题详情页进入");
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    setPaper(null);
    setResult(null);
    setDrafts({});
    startPractice({ mistakeId, topicId, count })
      .then((response) => {
        if (active) {
          setPaper(response);
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
  }, [mistakeId, topicId, count, reloadKey]);

  function setAnswer(questionId: string, answer: string) {
    setDrafts((previous) => ({
      ...previous,
      [questionId]: {
        answer,
        correct: previous[questionId]?.correct ?? null,
      },
    }));
  }

  function setVerdict(questionId: string, correct: boolean) {
    setDrafts((previous) => ({
      ...previous,
      [questionId]: {
        answer: previous[questionId]?.answer ?? "",
        correct,
      },
    }));
  }

  async function handleSubmit() {
    if (!paper || !paper.topic_id || busy || result) {
      return;
    }
    const items = paper.items.map((question) => {
      const entry = drafts[question.question_id];
      const answer = entry?.answer.trim() ? entry.answer.trim() : null;
      return {
        question_id: question.question_id,
        answer,
        correct: question.mode === "self_eval" ? entry?.correct ?? null : null,
      };
    });
    if (!items.some((entry) => entry.answer || entry.correct !== null)) {
      setError("至少作答一题（或对解答大题自评）后再提交");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setResult(
        await submitPractice({
          topic_id: paper.topic_id,
          seed: paper.seed,
          count: paper.count,
          mistake_id: mistakeId,
          items,
        }),
      );
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  function statusFor(question: QuizQuestionView) {
    return result?.items.find(
      (entry) => entry.question_id === question.question_id,
    );
  }

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center" wrap="wrap">
        <Title order={2}>加练同类题</Title>
        <Group gap="xs">
          {mistakeId !== undefined && (
            <Button
              variant="subtle"
              onClick={() => navigate(`/mistakes/${mistakeId}`)}
            >
              返回错题 #{mistakeId}
            </Button>
          )}
          <Button variant="subtle" onClick={() => navigate("/records")}>
            练习记录
          </Button>
        </Group>
      </Group>

      <Text size="sm" c="dimmed">
        加练结果只写“练习记录”：不进错题本、不影响掌握度、复习排期与打卡。
        客观题由服务端判分，解答大题或依赖图形请在纸上完成后自评。
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

      {!loading && paper && paper.bank_gap && (
        <Alert color="gray" variant="light" title="该知识点暂无同类题">
          {paper.message ?? "该知识点暂无同类题"}；可以先重做原题，或请家长在题库页录入同类题。
        </Alert>
      )}

      {!loading && paper && !paper.bank_gap && (
        <Stack gap="sm">
          <Group gap="xs" wrap="wrap">
            <Badge variant="light">知识点 {paper.topic_id}</Badge>
            <Badge color="gray" variant="light">
              seed {paper.seed}
            </Badge>
            <Badge color="blue" variant="light">
              可答题 {paper.answerable_total}/{paper.pool_total}
            </Badge>
            {paper.coverage === "thin" && (
              <Badge color="yellow" variant="light">
                该学科题库覆盖偏薄
              </Badge>
            )}
          </Group>

          {paper.items.map((question, index) => {
            const status = statusFor(question);
            const entry = drafts[question.question_id];
            return (
              <Stack key={question.question_id} gap={6}>
                <QuizQuestionCard
                  question={question}
                  index={index}
                  answer={entry?.answer ?? ""}
                  onAnswer={(value) => setAnswer(question.question_id, value)}
                  disabled={result !== null}
                />
                {question.mode === "self_eval" && (
                  <Group gap="xs">
                    <Text size="xs" c="dimmed">
                      纸上完成，自评：
                    </Text>
                    <Button
                      size="compact-xs"
                      color="green"
                      variant={entry?.correct === true ? "filled" : "light"}
                      onClick={() => setVerdict(question.question_id, true)}
                      disabled={result !== null}
                    >
                      做对了
                    </Button>
                    <Button
                      size="compact-xs"
                      color="red"
                      variant={entry?.correct === false ? "filled" : "light"}
                      onClick={() => setVerdict(question.question_id, false)}
                      disabled={result !== null}
                    >
                      没做对
                    </Button>
                  </Group>
                )}
                {status && (
                  <Group gap={6}>
                    <Badge
                      color={STATUS_LABELS[status.status].color}
                      variant="light"
                    >
                      {STATUS_LABELS[status.status].label}
                    </Badge>
                    <Text size="xs" c="dimmed">
                      {status.mode === "system" ? "服务端判分" : "学生自评"}
                    </Text>
                    {status.reused && (
                      <Badge color="blue" variant="light">
                        已有记录
                      </Badge>
                    )}
                  </Group>
                )}
              </Stack>
            );
          })}

          {result && result.items.some((item) => item.reused) && (
            <Alert color="blue" variant="light" title="这一组已经提交过">
              同题重复提交不会新增记录，下面显示的是已有作答。
            </Alert>
          )}

          {result ? (
            <Group>
              <Badge color="green" variant="light">
                答对 {result.correct}
              </Badge>
              <Badge color="red" variant="light">
                答错 {result.wrong}
              </Badge>
              <Button variant="light" onClick={() => navigate("/records")}>
                回看练习记录
              </Button>
              <Button variant="subtle" onClick={() => setReloadKey((v) => v + 1)}>
                再练一组
              </Button>
            </Group>
          ) : (
            <Group>
              <Button onClick={() => void handleSubmit()} loading={busy}>
                提交加练
              </Button>
              <Text size="xs" c="dimmed">
                留空的题会跳过；提交后只写练习记录。
              </Text>
            </Group>
          )}
        </Stack>
      )}

      {!loading && !paper && !error && (
        <Alert color="gray" variant="light">
          暂时没有可用的练习卷。
        </Alert>
      )}
    </Stack>
  );
}
