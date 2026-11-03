import {
  Alert,
  Badge,
  Button,
  Card,
  Divider,
  Group,
  Loader,
  Progress,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useEffect, useState } from "react";

import { errorMessage } from "../api/client";
import {
  createRecitation,
  getDashboard,
  getDueRecitations,
  listRecitations,
  reviewRecitation,
  updateRecitation,
} from "../api/endpoints";
import type {
  RecitationDueItem,
  RecitationDueResponse,
  RecitationItem,
  RecitationListResponse,
  RecitationVerdict,
} from "../api/types";
import { toISODate } from "../lib/dates";
import { useParentSession } from "../parent/ParentSession";

export default function RecitationsPage() {
  const { unlocked } = useParentSession();
  const [due, setDue] = useState<RecitationDueResponse | null>(null);
  const [items, setItems] = useState<RecitationListResponse | null>(null);
  const [progress, setProgress] = useState<{ today: number; limit: number } | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [lastResult, setLastResult] = useState<string | null>(null);
  const [revealed, setRevealed] = useState<Record<number, boolean>>({});

  const [subject, setSubject] = useState("英语");
  const [prompt, setPrompt] = useState("");
  const [answer, setAnswer] = useState("");
  const [unit, setUnit] = useState("");
  const [adding, setAdding] = useState(false);

  async function load(showSpinner = true) {
    if (showSpinner) {
      setLoading(true);
    }
    try {
      const today = toISODate(new Date());
      const [dueResponse, listResponse, dashboard] = await Promise.all([
        getDueRecitations(today),
        listRecitations({ limit: 200 }),
        getDashboard({ today }),
      ]);
      setDue(dueResponse);
      setItems(listResponse);
      setProgress({
        today: dashboard.recitations_today,
        limit: dashboard.recitation_limit,
      });
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

  async function mark(itemId: number, verdict: RecitationVerdict) {
    if (busyId !== null) {
      return;
    }
    setBusyId(itemId);
    setActionError(null);
    setLastResult(null);
    try {
      const result = await reviewRecitation(itemId, { verdict });
      setLastResult(
        result.graduated
          ? `「${result.item.prompt}」已背熟并毕业，不用再排期。`
          : `「${result.item.prompt}」下次复习：${result.scheduled_next ?? "—"}（第 ${result.rung + 1} 档）`,
      );
      await load(false);
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setBusyId(null);
    }
  }

  async function addItem() {
    if (adding) {
      return;
    }
    if (!subject.trim() || !prompt.trim()) {
      setActionError("请填写学科与背诵条目");
      return;
    }
    setAdding(true);
    setActionError(null);
    try {
      await createRecitation({
        subject: subject.trim(),
        prompt: prompt.trim(),
        answer: answer.trim() || null,
        unit: unit.trim() || null,
      });
      setPrompt("");
      setAnswer("");
      setUnit("");
      await load(false);
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setAdding(false);
    }
  }

  async function toggleStatus(item: RecitationItem) {
    if (busyId !== null) {
      return;
    }
    setBusyId(item.id);
    setActionError(null);
    try {
      await updateRecitation(item.id, {
        status: item.status === "active" ? "retired" : "active",
      });
      await load(false);
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setBusyId(null);
    }
  }

  const goal = progress?.limit ?? 0;
  const todayDone = progress?.today ?? 0;

  return (
    <Stack gap="md">
      <Stack gap={4}>
        <Title order={2}>英语背诵</Title>
        <Text size="sm" c="dimmed">
          家长手动录入条目，孩子按记忆阶梯自评（1/3/7/14/30 天）。
          “记得”进一档，“没记住”保持当前档；背诵不是错题，也不计入掌握度。
        </Text>
      </Stack>

      {actionError && (
        <Alert color="red" variant="light">
          {actionError}
        </Alert>
      )}
      {lastResult && (
        <Alert color="teal" variant="light">
          {lastResult}
        </Alert>
      )}
      {error && (
        <Alert color="red" variant="light" title="加载失败">
          {error}
        </Alert>
      )}

      {loading ? (
        <Group justify="center" py="xl">
          <Loader />
        </Group>
      ) : (
        <>
          <Card withBorder>
            <Stack gap="sm">
              <Group justify="space-between" align="center" wrap="wrap">
                <Text fw={600}>今日背诵</Text>
                <Text size="sm" c="dimmed">
                  {todayDone}/{goal} 已完成 · 今日到期 {due?.due_total ?? 0} 条
                </Text>
              </Group>
              <Progress
                value={goal > 0 ? Math.min(100, (todayDone / goal) * 100) : 0}
                color={goal > 0 && todayDone >= goal ? "teal" : "blue"}
                radius="xl"
                aria-label={`今日背诵进度 ${todayDone}/${goal}`}
              />
              {due && due.due_total === 0 ? (
                <Text size="sm" c="dimmed">
                  今天没有到期条目。新录入的条目当天就会出现。
                </Text>
              ) : (
                <Text size="xs" c="dimmed">
                  先背，再点“记得 / 没记住”；同一天重复点不会重复计数。
                </Text>
              )}
            </Stack>
          </Card>

          {due?.items.map((entry: RecitationDueItem) => {
            const shown = revealed[entry.item.id] ?? false;
            return (
              <Card key={entry.item.id} withBorder>
                <Stack gap="sm">
                  <Group justify="space-between" align="flex-start" wrap="wrap">
                    <Group gap="xs" wrap="wrap">
                      <Badge variant="light">{entry.item.subject}</Badge>
                      {entry.item.unit && (
                        <Badge color="gray" variant="light">
                          {entry.item.unit}
                        </Badge>
                      )}
                      <Badge color="grape" variant="light">
                        第 {entry.rung + 1} 档
                      </Badge>
                    </Group>
                    <Text size="xs" c="dimmed">
                      {entry.reviewed_on
                        ? `上次自评 ${entry.reviewed_on}`
                        : "新条目"}
                    </Text>
                  </Group>
                  <Text size="lg" fw={600} style={{ whiteSpace: "pre-wrap" }}>
                    {entry.item.prompt}
                  </Text>
                  {entry.item.answer && (
                    <Group gap="xs" align="center" wrap="wrap">
                      <Button
                        size="compact-xs"
                        variant="subtle"
                        onClick={() =>
                          setRevealed((current) => ({
                            ...current,
                            [entry.item.id]: !shown,
                          }))
                        }
                      >
                        {shown ? "收起答案" : "看答案"}
                      </Button>
                      {shown && (
                        <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
                          {entry.item.answer}
                        </Text>
                      )}
                    </Group>
                  )}
                  <Group gap="xs">
                    <Button
                      color="teal"
                      onClick={() => void mark(entry.item.id, "remembered")}
                      loading={busyId === entry.item.id}
                      disabled={busyId !== null}
                    >
                      记得
                    </Button>
                    <Button
                      color="orange"
                      variant="light"
                      onClick={() => void mark(entry.item.id, "forgot")}
                      loading={busyId === entry.item.id}
                      disabled={busyId !== null}
                    >
                      没记住
                    </Button>
                  </Group>
                </Stack>
              </Card>
            );
          })}

          <Divider my="sm" />

          {!unlocked && (
            <Alert color="gray" variant="light" title="条目维护属于家长操作">
              在右上角「家长区」输入 PIN 解锁后可新增、编辑或停用背诵条目；
              孩子的今日卡片不受影响。
            </Alert>
          )}

          {unlocked && (
            <Card withBorder>
              <Stack gap="sm">
                <Group justify="space-between" align="center" wrap="wrap">
                  <Text fw={600}>家长维护</Text>
                  <Text size="xs" c="dimmed">
                    同科同条目唯一；停用后不再出现在今日卡片
                  </Text>
                </Group>
                <SimpleGrid cols={{ base: 1, sm: 2, md: 4 }}>
                  <TextInput
                    label="学科"
                    value={subject}
                    onChange={(event) => setSubject(event.currentTarget.value)}
                    placeholder="英语"
                  />
                  <TextInput
                    label="背诵条目"
                    value={prompt}
                    onChange={(event) => setPrompt(event.currentTarget.value)}
                    placeholder="abandon"
                  />
                  <TextInput
                    label="答案（可选）"
                    value={answer}
                    onChange={(event) => setAnswer(event.currentTarget.value)}
                    placeholder="放弃"
                  />
                  <TextInput
                    label="单元（可选）"
                    value={unit}
                    onChange={(event) => setUnit(event.currentTarget.value)}
                    placeholder="Unit 1"
                  />
                </SimpleGrid>
                <Group>
                  <Button
                    onClick={() => void addItem()}
                    loading={adding}
                    disabled={!subject.trim() || !prompt.trim()}
                  >
                    添加条目
                  </Button>
                </Group>

                {items && items.items.length > 0 && (
                  <Table.ScrollContainer minWidth={520}>
                    <Table striped highlightOnHover>
                      <Table.Thead>
                        <Table.Tr>
                          <Table.Th>学科</Table.Th>
                          <Table.Th>条目</Table.Th>
                          <Table.Th>答案</Table.Th>
                          <Table.Th>单元</Table.Th>
                          <Table.Th>状态</Table.Th>
                          <Table.Th />
                        </Table.Tr>
                      </Table.Thead>
                      <Table.Tbody>
                        {items.items.map((item) => (
                          <Table.Tr key={item.id}>
                            <Table.Td>{item.subject}</Table.Td>
                            <Table.Td>
                              <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
                                {item.prompt}
                              </Text>
                            </Table.Td>
                            <Table.Td>{item.answer ?? "—"}</Table.Td>
                            <Table.Td>{item.unit ?? "—"}</Table.Td>
                            <Table.Td>
                              <Badge
                                color={item.status === "active" ? "teal" : "gray"}
                                variant="light"
                              >
                                {item.status === "active" ? "启用" : "已停用"}
                              </Badge>
                            </Table.Td>
                            <Table.Td>
                              <Button
                                size="compact-xs"
                                variant="light"
                                color={item.status === "active" ? "orange" : "teal"}
                                onClick={() => void toggleStatus(item)}
                                loading={busyId === item.id}
                                disabled={busyId !== null}
                              >
                                {item.status === "active" ? "停用" : "启用"}
                              </Button>
                            </Table.Td>
                          </Table.Tr>
                        ))}
                      </Table.Tbody>
                    </Table>
                  </Table.ScrollContainer>
                )}
              </Stack>
            </Card>
          )}
        </>
      )}
    </Stack>
  );
}
