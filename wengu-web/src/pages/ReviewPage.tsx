import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { errorMessage } from "../api/client";
import { completeReview, getDueReviews } from "../api/endpoints";
import type { CompleteReviewResponse, DueReviewItem, DueReviewResponse } from "../api/types";
import MathText from "../components/MathText";

export default function ReviewPage() {
  const navigate = useNavigate();
  const [due, setDue] = useState<DueReviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [completingId, setCompletingId] = useState<number | null>(null);
  const [results, setResults] = useState<CompleteReviewResponse[]>([]);

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

  async function complete(item: DueReviewItem, correct: boolean) {
    if (completingId !== null) {
      return;
    }
    setCompletingId(item.schedule_id);
    setActionError(null);
    try {
      const result = await completeReview(item.mistake_id, {
        schedule_id: item.schedule_id,
        correct,
      });
      setResults((previous) => [result, ...previous]);
      setDue((previous) =>
        previous
          ? {
              ...previous,
              items: previous.items.filter(
                (entry) => entry.schedule_id !== item.schedule_id,
              ),
              total: Math.max(0, previous.total - 1),
            }
          : previous,
      );
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setCompletingId(null);
    }
  }

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center">
        <Title order={2}>复习</Title>
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
          key={result.schedule_id}
          color={result.graduated ? "green" : "blue"}
          variant="light"
          title={result.graduated ? "这道题已毕业" : "复习完成"}
        >
          <Stack gap={4}>
            {result.graduated ? (
              <Text size="sm">
                连续答对达到要求，之后不再排复习；错题仍保留在错题本。
              </Text>
            ) : (
              <Text size="sm">
                下一次复习：{result.due_on ?? "待定"}
                {result.interval_days !== null
                  ? `（间隔 ${result.interval_days} 天）`
                  : ""}
              </Text>
            )}
            <Text size="xs" c="dimmed">
              掌握度 {Math.round(result.mastery * 100)}% · 等级{" "}
              {result.state.rung + 1} · 连对 {result.state.trailing_correct}
            </Text>
          </Stack>
        </Alert>
      ))}

      {!loading && !error && due && due.items.length === 0 && (
        <Alert color="blue" variant="light" title="今天没有到期复习">
          到期时间按实际完成日起算；可以去采集页继续录题，或到错题本补标签。
        </Alert>
      )}

      {due?.items.map((item) => (
        <Card key={item.schedule_id} withBorder>
          <Stack gap="sm">
            <Group justify="space-between" align="flex-start">
              <Badge variant="light">复习 #{item.mistake_id}</Badge>
              <Text size="xs" c="dimmed">
                到期 {item.due_date} · 等级 {item.rung + 1} · 基础间隔{" "}
                {item.base_interval_days} 天
              </Text>
            </Group>
            <MathText text={item.problem_text || "（题目文本缺失）"} />
            <Group>
              <Button
                color="green"
                onClick={() => void complete(item, true)}
                loading={completingId === item.schedule_id}
                disabled={completingId !== null}
              >
                答对了
              </Button>
              <Button
                color="red"
                variant="light"
                onClick={() => void complete(item, false)}
                loading={completingId === item.schedule_id}
                disabled={completingId !== null}
              >
                没答对
              </Button>
              <Button
                variant="subtle"
                onClick={() => navigate(`/mistakes/${item.mistake_id}`)}
              >
                查看错题
              </Button>
              <Button
                variant="subtle"
                onClick={() =>
                  navigate(
                    `/explain?source_kind=mistake&source_id=${item.mistake_id}`,
                  )
                }
              >
                卡住了，看讲解
              </Button>
            </Group>
          </Stack>
        </Card>
      ))}
    </Stack>
  );
}
