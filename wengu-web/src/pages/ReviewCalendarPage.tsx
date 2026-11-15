import {
  Alert,
  Anchor,
  Badge,
  Box,
  Button,
  Card,
  Divider,
  Group,
  Loader,
  SimpleGrid,
  Stack,
  Text,
  Title,
  UnstyledButton,
} from "@mantine/core";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { errorMessage } from "../api/client";
import { getReviewCalendar } from "../api/endpoints";
import type { ReviewCalendarResponse, ReviewTask } from "../api/types";
import { shiftDays, toISODate, weekdayNumber } from "../lib/dates";

const WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];

const KIND_LABELS: Record<ReviewTask, string> = {
  quiz: "同类题考核",
  self_eval: "纸上自评",
  redo: "原题重做",
};

const KIND_COLORS: Record<ReviewTask, string> = {
  quiz: "blue",
  self_eval: "grape",
  redo: "gray",
};

const DONE_LABELS: Record<string, string> = {
  attempt_correct: "答对",
  attempt_wrong: "答错",
  recitation_reviewed: "背诵自评",
  pomodoro_completed: "番茄钟完成",
  review_scheduled: "排复习",
  mistake_labeled: "标注错因",
  mistake_voided: "作废错题",
  mistake_reactivated: "恢复错题",
  mistake_primary_topic_set: "设主考点",
};

function firstOfMonth(value: Date): Date {
  return new Date(value.getFullYear(), value.getMonth(), 1);
}

function dayLabel(iso: string): string {
  const date = new Date(`${iso}T00:00:00`);
  const weekday = WEEKDAY_LABELS[weekdayNumber(date) - 1];
  return `${Number(iso.slice(5, 7))}月${Number(iso.slice(8, 10))}日 · ${weekday}`;
}

export default function ReviewCalendarPage() {
  const navigate = useNavigate();
  const [anchor, setAnchor] = useState<Date>(() => firstOfMonth(new Date()));
  const [data, setData] = useState<ReviewCalendarResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const { cells, gridStartISO, gridEndISO, monthLabel } = useMemo(() => {
    const year = anchor.getFullYear();
    const month = anchor.getMonth();
    const first = new Date(year, month, 1);
    const last = new Date(year, month + 1, 0);
    const start = shiftDays(first, -(weekdayNumber(first) - 1));
    const end = shiftDays(last, 7 - weekdayNumber(last));
    const count =
      Math.round((end.getTime() - start.getTime()) / 86_400_000) + 1;
    return {
      cells: Array.from({ length: count }, (_, index) => shiftDays(start, index)),
      gridStartISO: toISODate(start),
      gridEndISO: toISODate(end),
      monthLabel: `${year}年${month + 1}月`,
    };
  }, [anchor]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const response = await getReviewCalendar({
          from: gridStartISO,
          to: gridEndISO,
        });
        if (cancelled) {
          return;
        }
        const map = new Map(response.days.map((day) => [day.date, day]));
        setData(response);
        setError(null);
        setSelected((prev) =>
          prev && map.has(prev)
            ? prev
            : map.has(response.today)
              ? response.today
              : null,
        );
      } catch (cause) {
        if (!cancelled) {
          setError(errorMessage(cause));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [gridStartISO, gridEndISO]);

  const dayMap = useMemo(
    () => new Map((data?.days ?? []).map((day) => [day.date, day])),
    [data],
  );
  const selectedDay = selected ? dayMap.get(selected) : undefined;
  const todayISO = toISODate(new Date());

  function goToday() {
    setAnchor(firstOfMonth(new Date()));
    setSelected(todayISO);
  }

  return (
    <Stack gap="md">
      <Stack gap={4}>
        <Title order={2}>复习日历</Title>
        <Text size="sm" c="dimmed">
          只读投影：计划来自复习排期、完成来自学习事实，按日归属。不是自动排课，
          也不生成任务；点任意一天查看当日清单，再去「复习考核」做题。
        </Text>
      </Stack>

      {error && (
        <Alert color="red" variant="light" title="加载失败">
          {error}
        </Alert>
      )}

      <Group justify="space-between" align="center" wrap="nowrap">
        <Button
          variant="default"
          size="compact-sm"
          onClick={() =>
            setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() - 1, 1))
          }
        >
          ‹ 上月
        </Button>
        <Title order={4}>{monthLabel}</Title>
        <Group gap="xs" wrap="nowrap">
          <Button variant="subtle" size="compact-sm" onClick={goToday}>
            回到今天
          </Button>
          <Button
            variant="default"
            size="compact-sm"
            onClick={() =>
              setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() + 1, 1))
            }
          >
            下月 ›
          </Button>
        </Group>
      </Group>

      {loading ? (
        <Group justify="center" py="xl">
          <Loader />
        </Group>
      ) : (
        <>
          <SimpleGrid cols={7} spacing={4}>
            {WEEKDAY_LABELS.map((label) => (
              <Text key={label} size="xs" c="dimmed" ta="center">
                {label}
              </Text>
            ))}
          </SimpleGrid>

          <SimpleGrid cols={7} spacing={4}>
            {cells.map((date) => {
              const iso = toISODate(date);
              const day = dayMap.get(iso);
              const planned = day?.planned ?? [];
              const plannedCount = planned.length;
              const overdueCount = planned.filter((p) => p.overdue).length;
              const doneCount = day?.done.length ?? 0;
              const inMonth = date.getMonth() === anchor.getMonth();
              const isToday = iso === (data?.today ?? todayISO);
              const isSelected = iso === selected;
              return (
                <UnstyledButton
                  key={iso}
                  onClick={() => setSelected(iso)}
                  aria-label={`${iso}，${plannedCount} 道计划`}
                  aria-pressed={isSelected}
                  style={{ width: "100%", minWidth: 0 }}
                >
                  <Box
                    p={4}
                    style={{
                      minWidth: 0,
                      overflow: "hidden",
                      minHeight: 58,
                      borderRadius: 8,
                      border: `1px solid ${
                        isSelected
                          ? "var(--mantine-primary-color-filled)"
                          : "var(--mantine-color-default-border)"
                      }`,
                      background: isSelected
                        ? "var(--mantine-primary-color-light)"
                        : isToday
                          ? "var(--mantine-color-default-hover)"
                          : undefined,
                      opacity: inMonth ? 1 : 0.45,
                    }}
                  >
                    <Text
                      size="xs"
                      ta="center"
                      fw={isToday ? 700 : 500}
                      c={inMonth ? undefined : "dimmed"}
                    >
                      {date.getDate()}
                    </Text>
                    {plannedCount > 0 && (
                      <Badge
                        size="xs"
                        variant="light"
                        color={overdueCount > 0 ? "red" : "blue"}
                        title={`${plannedCount} 道计划`}
                        style={{
                          display: "block",
                          maxWidth: "100%",
                          margin: "2px auto 0",
                        }}
                      >
                        {plannedCount} 道
                      </Badge>
                    )}
                    {doneCount > 0 && (
                      <Text
                        size="xs"
                        c="teal.6"
                        ta="center"
                        style={{ fontSize: 10 }}
                      >
                        ✓{doneCount}
                      </Text>
                    )}
                  </Box>
                </UnstyledButton>
              );
            })}
          </SimpleGrid>

          <Text size="xs" c="dimmed">
            格中「N 道」= 当日计划道数（红色含逾期）；✓N = 当日完成事实数。
          </Text>

          <Card withBorder>
            {selectedDay ? (
              <Stack gap="sm">
                <Group justify="space-between" align="center" wrap="wrap">
                  <Group gap="xs">
                    <Text fw={600}>{dayLabel(selectedDay.date)}</Text>
                    <Badge variant="light" color="blue">
                      {selectedDay.planned.length} 道计划
                    </Badge>
                  </Group>
                  <Button
                    size="compact-sm"
                    onClick={() => navigate("/review")}
                  >
                    去复习
                  </Button>
                </Group>

                {selectedDay.planned.length === 0 ? (
                  <Text size="sm" c="dimmed">
                    当日无计划排期。
                  </Text>
                ) : (
                  <Stack gap={6}>
                    {selectedDay.planned.map((item) => (
                      <Group
                        key={`${item.mistake_id}-${item.due_date}`}
                        gap="xs"
                        wrap="wrap"
                      >
                        <Badge
                          variant="light"
                          color={KIND_COLORS[item.kind]}
                          size="sm"
                        >
                          {KIND_LABELS[item.kind]}
                        </Badge>
                        {item.overdue && (
                          <Badge variant="light" color="red" size="sm">
                            逾期
                          </Badge>
                        )}
                        {item.completed && (
                          <Badge variant="light" color="teal" size="sm">
                            已完成
                          </Badge>
                        )}
                        <Anchor
                          component={Link}
                          to={`/mistakes/${item.mistake_id}`}
                          size="sm"
                        >
                          错题 #{item.mistake_id}
                        </Anchor>
                        <Text size="xs" c="dimmed">
                          到期 {item.due_date}
                        </Text>
                      </Group>
                    ))}
                  </Stack>
                )}

                <Divider />

                <Text fw={600} size="sm">
                  当日完成事实
                </Text>
                {selectedDay.done.length === 0 ? (
                  <Text size="sm" c="dimmed">
                    无。
                  </Text>
                ) : (
                  <Group gap="xs" wrap="wrap">
                    {selectedDay.done.map((item, index) => (
                      <Group
                        key={`${item.type}-${item.mistake_id ?? "none"}-${index}`}
                        gap={4}
                        wrap="nowrap"
                      >
                        <Badge variant="light" color="gray" size="sm">
                          {DONE_LABELS[item.type] ?? item.type}
                        </Badge>
                        {item.mistake_id !== null && (
                          <Anchor
                            component={Link}
                            to={`/mistakes/${item.mistake_id}`}
                            size="xs"
                          >
                            #{item.mistake_id}
                          </Anchor>
                        )}
                      </Group>
                    ))}
                  </Group>
                )}
              </Stack>
            ) : (
              <Text size="sm" c="dimmed">
                点月历中任意一天，查看当日计划与完成清单。
              </Text>
            )}
          </Card>
        </>
      )}
    </Stack>
  );
}