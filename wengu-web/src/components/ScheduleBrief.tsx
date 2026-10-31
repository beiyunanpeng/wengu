import { Badge, Card, Group, SimpleGrid, Stack, Text } from "@mantine/core";
import { useEffect, useState } from "react";

import { errorMessage } from "../api/client";
import { getCalendarEvents, getTimetable } from "../api/endpoints";
import type { CalendarEvent, CalendarKind, TimetableSlot } from "../api/types";
import { shiftDays, toISODate, weekdayNumber } from "../lib/dates";

export const KIND_LABELS: Record<CalendarKind, string> = {
  exam: "考试",
  competition: "竞赛",
  leave: "请假",
  other: "其它",
};

const KIND_COLORS: Record<CalendarKind, string> = {
  exam: "red",
  competition: "grape",
  leave: "gray",
  other: "blue",
};

/** 头部摘要：今日课程 + 未来 7 天硬事件（只读，孩子与家长同见）。 */
export default function ScheduleBrief() {
  const [slots, setSlots] = useState<TimetableSlot[]>([]);
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const today = new Date();
    void (async () => {
      try {
        const [timetable, calendar] = await Promise.all([
          getTimetable(),
          getCalendarEvents({
            from: toISODate(today),
            to: toISODate(shiftDays(today, 7)),
          }),
        ]);
        if (!cancelled) {
          setSlots(timetable.items);
          setEvents(calendar.items);
          setError(null);
        }
      } catch (cause) {
        if (!cancelled) {
          setError(errorMessage(cause));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const weekday = weekdayNumber(new Date());
  const todaySlots = slots
    .filter((slot) => slot.weekday === weekday)
    .sort((left, right) => left.period - right.period);
  const hardEvents = events.filter((event) => event.kind !== "leave");

  return (
    <Card withBorder padding="sm">
      <SimpleGrid cols={{ base: 1, sm: 2 }}>
        <Stack gap={4}>
          <Text size="xs" c="dimmed">
            今日课程
          </Text>
          {todaySlots.length === 0 ? (
            <Text size="sm" c="dimmed">
              今天没有课
            </Text>
          ) : (
            <Group gap="xs" wrap="wrap">
              {todaySlots.map((slot) => (
                <Badge key={slot.id} variant="light">
                  第{slot.period}节 {slot.subject}
                </Badge>
              ))}
            </Group>
          )}
        </Stack>
        <Stack gap={4}>
          <Text size="xs" c="dimmed">
            未来 7 天硬事件
          </Text>
          {hardEvents.length === 0 ? (
            <Text size="sm" c="dimmed">
              未来 7 天没有考试/竞赛
            </Text>
          ) : (
            <Stack gap={2}>
              {hardEvents.map((event) => (
                <Group key={event.id} gap="xs" wrap="nowrap">
                  <Badge
                    color={KIND_COLORS[event.kind]}
                    variant="light"
                    size="sm"
                  >
                    {KIND_LABELS[event.kind]}
                  </Badge>
                  <Text size="sm">
                    {event.date} · {event.title}
                    {event.subject ? `（${event.subject}）` : ""}
                  </Text>
                </Group>
              ))}
            </Stack>
          )}
        </Stack>
      </SimpleGrid>
      {error && (
        <Text size="xs" c="red" mt={4}>
          课表/日历读取失败：{error}
        </Text>
      )}
    </Card>
  );
}
