import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Pagination,
  SegmentedControl,
  Stack,
  Tabs,
  Text,
  Title,
} from "@mantine/core";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { errorMessage } from "../api/client";
import { listAttempts, listPracticeRecords } from "../api/endpoints";
import type { AttemptInfo, PracticeRecordInfo } from "../api/types";
import MathText from "../components/MathText";

const PAGE_SIZE = 20;
const PRACTICE_KIND_LABELS: Record<string, string> = {
  variant: "变式",
  extra: "加练",
};

function CorrectnessBadge({ correct }: { correct: boolean | null }) {
  if (correct === null) {
    return (
      <Badge color="gray" variant="light">
        未判
      </Badge>
    );
  }
  return (
    <Badge color={correct ? "green" : "red"} variant="light">
      {correct ? "答对" : "答错"}
    </Badge>
  );
}

export default function RecordsPage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState<string | null>("quiz");

  const [attempts, setAttempts] = useState<AttemptInfo[]>([]);
  const [attemptTotal, setAttemptTotal] = useState(0);
  const [attemptOffset, setAttemptOffset] = useState(0);
  const [attemptLoading, setAttemptLoading] = useState(false);
  const [attemptError, setAttemptError] = useState<string | null>(null);

  const [practiceKind, setPracticeKind] = useState<"all" | "variant" | "extra">(
    "all",
  );
  const [practice, setPractice] = useState<PracticeRecordInfo[]>([]);
  const [practiceTotal, setPracticeTotal] = useState(0);
  const [practiceOffset, setPracticeOffset] = useState(0);
  const [practiceLoading, setPracticeLoading] = useState(false);
  const [practiceError, setPracticeError] = useState<string | null>(null);

  useEffect(() => {
    if (tab !== "quiz") {
      return;
    }
    let active = true;
    setAttemptLoading(true);
    listAttempts({
      source: "system_quiz",
      limit: PAGE_SIZE,
      offset: attemptOffset,
    })
      .then((response) => {
        if (!active) {
          return;
        }
        setAttempts(response.items);
        setAttemptTotal(response.total);
        setAttemptError(null);
      })
      .catch((cause: unknown) => {
        if (active) {
          setAttemptError(errorMessage(cause));
        }
      })
      .finally(() => {
        if (active) {
          setAttemptLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [tab, attemptOffset]);

  useEffect(() => {
    if (tab !== "practice") {
      return;
    }
    let active = true;
    setPracticeLoading(true);
    listPracticeRecords({
      kind: practiceKind === "all" ? undefined : practiceKind,
      limit: PAGE_SIZE,
      offset: practiceOffset,
    })
      .then((response) => {
        if (!active) {
          return;
        }
        setPractice(response.items);
        setPracticeTotal(response.total);
        setPracticeError(null);
      })
      .catch((cause: unknown) => {
        if (active) {
          setPracticeError(errorMessage(cause));
        }
      })
      .finally(() => {
        if (active) {
          setPracticeLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [tab, practiceKind, practiceOffset]);

  return (
    <Stack gap="md">
      <Title order={2}>练习记录</Title>
      <Text size="sm" c="dimmed">
        只读回看：同类题考核结果与变式/加练作答都不进错题本、不排复习。
      </Text>

      <Tabs value={tab} onChange={setTab}>
        <Tabs.List>
          <Tabs.Tab value="quiz">同类题考核</Tabs.Tab>
          <Tabs.Tab value="practice">变式 / 加练</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="quiz" pt="md">
          <Stack gap="sm">
            <Group justify="space-between">
              <Text size="sm" c="dimmed">
                共 {attemptTotal} 条（source=system_quiz）
              </Text>
              <Badge color="blue" variant="light">
                考核结果计入掌握度，不新建错题
              </Badge>
            </Group>
            {attemptLoading && (
              <Group justify="center" py="xl">
                <Loader />
              </Group>
            )}
            {attemptError && (
              <Alert color="red" variant="light" title="加载失败">
                {attemptError}
              </Alert>
            )}
            {!attemptLoading && !attemptError && attempts.length === 0 && (
              <Alert color="gray" variant="light" title="还没有考核记录">
                到期考核或手动组卷提交后，服务端判分结果会出现在这里。
              </Alert>
            )}
            {attempts.map((item) => (
              <Card key={item.id} withBorder>
                <Stack gap="xs">
                  <Group justify="space-between" align="flex-start" wrap="wrap">
                    <Group gap="xs">
                      <CorrectnessBadge correct={item.is_correct} />
                      {item.mistake_id !== null ? (
                        <Badge variant="outline">错题 #{item.mistake_id}</Badge>
                      ) : (
                        <Badge color="blue" variant="outline">
                          手动组卷
                        </Badge>
                      )}
                      {item.topic_id && (
                        <Badge color="gray" variant="light">
                          {item.topic_id}
                        </Badge>
                      )}
                    </Group>
                    <Text size="xs" c="dimmed">
                      {new Date(item.created_at).toLocaleString()}
                    </Text>
                  </Group>
                  <MathText text={item.problem_text || "（题目文本缺失）"} />
                  <Text size="sm" c="dimmed">
                    {item.answer_text
                      ? `孩子的作答：${item.answer_text}`
                      : "作答不入库（考核只记对错）"}
                  </Text>
                  {item.mistake_id !== null && (
                    <Group>
                      <Button
                        size="compact-sm"
                        variant="subtle"
                        onClick={() => navigate(`/mistakes/${item.mistake_id}`)}
                      >
                        查看来源错题
                      </Button>
                    </Group>
                  )}
                </Stack>
              </Card>
            ))}
            {attemptTotal > PAGE_SIZE && (
              <Group justify="center">
                <Pagination
                  total={Math.ceil(attemptTotal / PAGE_SIZE)}
                  value={Math.floor(attemptOffset / PAGE_SIZE) + 1}
                  onChange={(page) => setAttemptOffset((page - 1) * PAGE_SIZE)}
                />
              </Group>
            )}
          </Stack>
        </Tabs.Panel>

        <Tabs.Panel value="practice" pt="md">
          <Stack gap="sm">
            <Group justify="space-between" wrap="wrap">
              <Text size="sm" c="dimmed">
                共 {practiceTotal} 条
              </Text>
              <SegmentedControl
                size="xs"
                value={practiceKind}
                onChange={(value) => {
                  setPracticeKind(value as "all" | "variant" | "extra");
                  setPracticeOffset(0);
                }}
                data={[
                  { value: "all", label: "全部" },
                  { value: "variant", label: "变式" },
                  { value: "extra", label: "加练" },
                ]}
              />
            </Group>
            {practiceLoading && (
              <Group justify="center" py="xl">
                <Loader />
              </Group>
            )}
            {practiceError && (
              <Alert color="red" variant="light" title="加载失败">
                {practiceError}
              </Alert>
            )}
            {!practiceLoading && !practiceError && practice.length === 0 && (
              <Alert color="gray" variant="light" title="还没有变式/加练记录">
                这些记录只作回看，不影响错题本与复习排期。
              </Alert>
            )}
            {practice.map((item) => (
              <Card key={item.id} withBorder>
                <Stack gap="xs">
                  <Group justify="space-between" align="flex-start" wrap="wrap">
                    <Group gap="xs">
                      <Badge variant="light">
                        {PRACTICE_KIND_LABELS[item.kind] ?? item.kind}
                      </Badge>
                      <CorrectnessBadge correct={item.is_correct} />
                    </Group>
                    <Text size="xs" c="dimmed">
                      {new Date(item.created_at).toLocaleString()}
                    </Text>
                  </Group>
                  <MathText text={item.problem_text} />
                  <Text size="sm" c="dimmed">
                    作答：{item.student_answer || "（未记录）"}
                  </Text>
                  {item.source_mistake_id && (
                    <Group>
                      <Button
                        size="compact-sm"
                        variant="subtle"
                        onClick={() =>
                          navigate(`/mistakes/${item.source_mistake_id}`)
                        }
                      >
                        查看来源错题 #{item.source_mistake_id}
                      </Button>
                    </Group>
                  )}
                </Stack>
              </Card>
            ))}
            {practiceTotal > PAGE_SIZE && (
              <Group justify="center">
                <Pagination
                  total={Math.ceil(practiceTotal / PAGE_SIZE)}
                  value={Math.floor(practiceOffset / PAGE_SIZE) + 1}
                  onChange={(page) =>
                    setPracticeOffset((page - 1) * PAGE_SIZE)
                  }
                />
              </Group>
            )}
          </Stack>
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
