import {
  Alert,
  Box,
  Card,
  Group,
  Loader,
  Progress,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { useEffect, useState } from "react";

import { errorMessage } from "../api/client";
import { getDashboard } from "../api/endpoints";
import type {
  DashboardConceptMastery,
  DashboardCurvePoint,
  DashboardResponse,
  DashboardStreak,
} from "../api/types";

const percent = (value: number) => `${Math.round(value * 100)}%`;

function MetricCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number;
  hint?: string;
}) {
  return (
    <Card withBorder padding="md">
      <Stack gap={2}>
        <Text size="xs" c="dimmed">
          {label}
        </Text>
        <Text size="xl" fw={700}>
          {value}
        </Text>
        {hint && (
          <Text size="xs" c="dimmed">
            {hint}
          </Text>
        )}
      </Stack>
    </Card>
  );
}

function MasteryCurve({ points }: { points: DashboardCurvePoint[] }) {
  if (points.length === 0) {
    return (
      <Alert color="gray" variant="light" title="暂无掌握度曲线">
        先在核对页确认知识点，复习作答后这里会从 learning_events 重算曲线。
      </Alert>
    );
  }

  const width = 640;
  const height = 180;
  const paddingX = 28;
  const paddingY = 20;
  const plotWidth = width - paddingX * 2;
  const plotHeight = height - paddingY * 2;
  const step = points.length > 1 ? plotWidth / (points.length - 1) : 0;
  const coords = points.map((point, index) => ({
    ...point,
    x: paddingX + step * index,
    y: height - paddingY - point.mastery * plotHeight,
  }));
  const polyline = coords
    .map(({ x, y }) => `${x.toFixed(1)},${y.toFixed(1)}`)
    .join(" ");
  const last = coords[coords.length - 1];

  return (
    <Stack gap={4}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={180}
        role="img"
        aria-label={`近 ${points.length} 天掌握度曲线`}
      >
        {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
          const y = height - paddingY - ratio * plotHeight;
          return (
            <line
              key={ratio}
              x1={paddingX}
              x2={width - paddingX}
              y1={y}
              y2={y}
              stroke="#e9ecef"
              strokeWidth={1}
            />
          );
        })}
        <polyline
          points={polyline}
          fill="none"
          stroke="#228be6"
          strokeWidth={2}
        />
        <circle cx={last.x} cy={last.y} r={3.5} fill="#228be6" />
      </svg>
      <Group justify="space-between">
        <Text size="xs" c="dimmed">
          {points[0].date}
        </Text>
        <Text size="xs" c="dimmed">
          当前 {percent(last.mastery)}
        </Text>
        <Text size="xs" c="dimmed">
          {last.date}
        </Text>
      </Group>
    </Stack>
  );
}

function ConceptTable({ concepts }: { concepts: DashboardConceptMastery[] }) {
  if (concepts.length === 0) {
    return (
      <Alert color="gray" variant="light">
        还没有已确认的知识点，掌握度暂不计算。
      </Alert>
    );
  }
  return (
    <Table.ScrollContainer minWidth={480}>
      <Table striped highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>知识点</Table.Th>
            <Table.Th>分类</Table.Th>
            <Table.Th w={180}>掌握度</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {concepts.map((item) => (
            <Table.Tr key={item.concept_id}>
              <Table.Td>{item.name}</Table.Td>
              <Table.Td>
                <Text size="sm" c="dimmed">
                  {item.category_name ?? item.category_id}
                </Text>
              </Table.Td>
              <Table.Td>
                <Group gap="xs" wrap="nowrap">
                  <Progress
                    value={item.mastery * 100}
                    size="sm"
                    style={{ flex: 1 }}
                  />
                  <Text size="xs" w={36} ta="right">
                    {percent(item.mastery)}
                  </Text>
                </Group>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

function StreakCalendar({ days }: { days: DashboardStreak["recent_days"] }) {
  const doneCount = days.filter((day) => day.done).length;
  return (
    <Stack gap={4}>
      <Group justify="space-between">
        <Text size="xs" c="dimmed">
          近 30 天
        </Text>
        <Text size="xs" c="dimmed">
          点亮 {doneCount} 天
        </Text>
      </Group>
      <Group
        gap={4}
        wrap="wrap"
        role="img"
        aria-label={`近 30 天打卡日历，已点亮 ${doneCount} 天`}
      >
        {days.map((day) => (
          <Box
            key={day.date}
            title={`${day.date}${day.done ? " · 已打卡" : ""}`}
            w={14}
            h={14}
            style={{
              borderRadius: 3,
              backgroundColor: day.done ? "#12b886" : "#e9ecef",
            }}
          />
        ))}
      </Group>
    </Stack>
  );
}

function StreakCard({ streak }: { streak: DashboardStreak }) {
  const status = streak.today_done
    ? "今天已打卡 ✓"
    : streak.current_streak > 0
      ? "今天还没打卡 · 连续纪录还留着"
      : "今天还没打卡 · 随时可以开始";
  return (
    <Card withBorder padding="md">
      <Stack gap="sm">
        <Group justify="space-between" wrap="wrap">
          <Text fw={600}>每日打卡</Text>
          <Text size="sm" fw={600} c={streak.today_done ? "teal" : "dimmed"}>
            {status}
          </Text>
        </Group>
        <Group gap="xl">
          <Stack gap={0}>
            <Text size="xs" c="dimmed">
              连续
            </Text>
            <Text size="lg" fw={700}>
              {streak.current_streak} 天
            </Text>
          </Stack>
          <Stack gap={0}>
            <Text size="xs" c="dimmed">
              最长连续
            </Text>
            <Text size="lg" fw={700}>
              {streak.longest_streak} 天
            </Text>
          </Stack>
          <Stack gap={0}>
            <Text size="xs" c="dimmed">
              累计学习
            </Text>
            <Text size="lg" fw={700}>
              {streak.learning_days_total} 天
            </Text>
          </Stack>
        </Group>
        <StreakCalendar days={streak.recent_days} />
        <Text size="xs" c="dimmed">
          当天做过任意一道题就算打卡（答错也算）；它只记录“来了”，不代表掌握程度。
        </Text>
      </Stack>
    </Card>
  );
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    getDashboard()
      .then((response) => {
        if (active) {
          setData(response);
          setError(null);
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
  }, []);

  if (loading) {
    return (
      <Group justify="center" py="xl">
        <Loader />
      </Group>
    );
  }

  if (error || !data) {
    return (
      <Alert color="red" variant="light" title="看板加载失败">
        {error ?? "未知错误"}
      </Alert>
    );
  }

  return (
    <Stack gap="md">
      <Stack gap={4}>
        <Title order={2}>看板</Title>
        <Text size="sm" c="dimmed">
          只读确定性统计：孩子与家长看同一份，全部从事件事实现算，不调模型。
        </Text>
      </Stack>

      <StreakCard streak={data.streak} />

      <SimpleGrid cols={{ base: 2, sm: 3, md: 6 }}>
        <MetricCard
          label="活跃错题"
          value={data.inventory.active}
          hint={`已作废 ${data.inventory.voided}`}
        />
        <MetricCard
          label="今日到期"
          value={data.due.today}
          hint={`逾期 ${data.due.overdue} · 合计 ${data.due.total}`}
        />
        <MetricCard label="本周完成复习" value={data.completion.reviews_this_week} />
        <MetricCard
          label="已毕业错题"
          value={data.completion.graduated_total}
          hint={`本周 ${data.completion.graduated_this_week}`}
        />
        <MetricCard
          label="申诉"
          value={data.governance.appeal_count}
          hint={`涉及 ${data.governance.appealed_gradings} 条批改`}
        />
        <MetricCard
          label="作废"
          value={data.governance.void_events}
          hint={`撤销 ${data.governance.reactivate_events} 次`}
        />
      </SimpleGrid>

      <SimpleGrid cols={{ base: 1, md: 2 }}>
        <Card withBorder padding="md">
          <Stack gap="sm">
            <Group justify="space-between">
              <Text fw={600}>掌握度曲线</Text>
              <Text size="sm" c="dimmed">
                近 {data.mastery.curve_days} 天 · 当前{" "}
                {percent(data.mastery.overall)}
              </Text>
            </Group>
            <MasteryCurve points={data.mastery.curve} />
            <Text size="xs" c="dimmed">
              每个点 = 当日之前所有作答事实重算后，已确认知识点的平均掌握度。
            </Text>
          </Stack>
        </Card>

        <Card withBorder padding="md">
          <Stack gap="sm">
            <Text fw={600}>知识点掌握度（弱项在前）</Text>
            <ConceptTable concepts={data.mastery.concepts} />
          </Stack>
        </Card>
      </SimpleGrid>

      <SimpleGrid cols={{ base: 1, md: 2 }}>
        <Card withBorder padding="md">
          <Stack gap="sm">
            <Group justify="space-between">
              <Text fw={600}>薄弱分布</Text>
              <Text size="sm" c="dimmed">
                未挂考点 {data.inventory.unassigned_active}
              </Text>
            </Group>
            {data.weak_subjects.length > 0 && (
              <Group gap="xs">
                {data.weak_subjects.map((item) => (
                  <Text key={item.subject} size="sm">
                    {item.subject} {item.active_mistakes}
                  </Text>
                ))}
              </Group>
            )}
            {data.weak_topics.length === 0 ? (
              <Alert color="gray" variant="light">
                暂无活跃错题。
              </Alert>
            ) : (
              <Table.ScrollContainer minWidth={420}>
                <Table striped highlightOnHover>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>知识点</Table.Th>
                      <Table.Th>学科</Table.Th>
                      <Table.Th>活跃错题</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {data.weak_topics.map((item) => (
                      <Table.Tr key={item.topic_id}>
                        <Table.Td>{item.name ?? item.topic_id}</Table.Td>
                        <Table.Td>{item.subject ?? "—"}</Table.Td>
                        <Table.Td>{item.active_mistakes}</Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Table.ScrollContainer>
            )}
          </Stack>
        </Card>

        <Card withBorder padding="md">
          <Stack gap="sm">
            <Group justify="space-between">
              <Text fw={600}>题库覆盖缺口</Text>
              <Text size="sm" c="dimmed">
                未挂考点排期 {data.bank_gap.unassigned_open}
              </Text>
            </Group>
            {data.bank_gap.topics.length === 0 ? (
              <Alert color="gray" variant="light">
                当前到期主考点都有 seed 题库题目。
              </Alert>
            ) : (
              <>
                <Table.ScrollContainer minWidth={420}>
                  <Table striped highlightOnHover>
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>知识点</Table.Th>
                        <Table.Th>活跃错题</Table.Th>
                        <Table.Th>未完成排期</Table.Th>
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {data.bank_gap.topics.map((item) => (
                        <Table.Tr key={item.topic_id}>
                          <Table.Td>
                            <Stack gap={0}>
                              <Text size="sm">{item.name ?? item.topic_id}</Text>
                              <Text size="xs" c="dimmed">
                                {item.subject ?? item.topic_id}
                              </Text>
                            </Stack>
                          </Table.Td>
                          <Table.Td>{item.active_mistakes}</Table.Td>
                          <Table.Td>{item.open_schedules}</Table.Td>
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                </Table.ScrollContainer>
                <Text size="xs" c="dimmed">
                  这些主考点在 seed 题库里 0 题，到期会退回原题重做；可通过教材包补题。
                </Text>
              </>
            )}
          </Stack>
        </Card>
      </SimpleGrid>

      <Card withBorder padding="md">
        <Group justify="space-between" wrap="wrap">
          <Text fw={600}>事件事实</Text>
          <Text size="sm" c="dimmed">
            共 {data.event_stats.total_events} 条 · 作答正确率{" "}
            {data.event_stats.attempt_accuracy === null
              ? "—"
              : percent(data.event_stats.attempt_accuracy)}{" "}
            · 对 {data.event_stats.attempts_correct} / 错{" "}
            {data.event_stats.attempts_wrong}
          </Text>
        </Group>
      </Card>
    </Stack>
  );
}
