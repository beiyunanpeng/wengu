import {
  Alert,
  Badge,
  Button,
  Card,
  Divider,
  Group,
  Loader,
  NumberInput,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useEffect, useState } from "react";

import { errorMessage } from "../api/client";
import {
  createCalendarEvent,
  createTimetableSlot,
  deleteCalendarEvent,
  deleteTimetableSlot,
  getCalendarEvents,
  getTimetable,
} from "../api/endpoints";
import type { CalendarEvent, CalendarKind, TimetableSlot } from "../api/types";
import { KIND_LABELS } from "../components/ScheduleBrief";
import { toISODate } from "../lib/dates";
import { useParentSession } from "../parent/ParentSession";

const WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];

const WEEKDAY_OPTIONS = WEEKDAY_LABELS.map((label, index) => ({
  value: String(index + 1),
  label,
}));

const KIND_OPTIONS = (
  ["exam", "competition", "leave", "other"] as CalendarKind[]
).map((kind) => ({ value: kind, label: KIND_LABELS[kind] }));

const KIND_COLORS: Record<CalendarKind, string> = {
  exam: "red",
  competition: "grape",
  leave: "gray",
  other: "blue",
};

export default function SchedulePage() {
  const { unlocked } = useParentSession();
  const [slots, setSlots] = useState<TimetableSlot[]>([]);
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [weekday, setWeekday] = useState<string>("1");
  const [period, setPeriod] = useState<string | number>(1);
  const [subject, setSubject] = useState("");
  const [note, setNote] = useState("");

  const [date, setDate] = useState(toISODate(new Date()));
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<string>("exam");
  const [eventSubject, setEventSubject] = useState("");
  const [eventNote, setEventNote] = useState("");

  async function load() {
    setLoading(true);
    try {
      const [timetable, calendar] = await Promise.all([
        getTimetable(),
        getCalendarEvents(),
      ]);
      setSlots(timetable.items);
      setEvents(calendar.items);
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

  async function addSlot() {
    if (busy) {
      return;
    }
    const periodValue = Number(period);
    if (!subject.trim()) {
      setActionError("请填写科目");
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      await createTimetableSlot({
        weekday: Number(weekday),
        period: periodValue,
        subject: subject.trim(),
        note: note.trim() || null,
      });
      setSubject("");
      setNote("");
      await load();
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  async function removeSlot(slotId: number) {
    if (busy) {
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      await deleteTimetableSlot(slotId);
      await load();
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  async function addEvent() {
    if (busy) {
      return;
    }
    if (!title.trim()) {
      setActionError("请填写事件标题");
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      await createCalendarEvent({
        date,
        title: title.trim(),
        kind: kind as CalendarKind,
        subject: eventSubject.trim() || null,
        note: eventNote.trim() || null,
      });
      setTitle("");
      setEventSubject("");
      setEventNote("");
      await load();
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  async function removeEvent(eventId: number) {
    if (busy) {
      return;
    }
    setBusy(true);
    setActionError(null);
    try {
      await deleteCalendarEvent(eventId);
      await load();
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  const periodValue = Number(period);
  const periodValid =
    Number.isInteger(periodValue) && periodValue >= 1 && periodValue <= 12;

  return (
    <Stack gap="md">
      <Stack gap={4}>
        <Title order={2}>课表 / 日历</Title>
        <Text size="sm" c="dimmed">
          课表与硬事件只是约束层：用来展示“今天有什么课、最近有什么考试”，
          并让考试日临时放宽复习上限；不会自动排课、不生成任务。
        </Text>
      </Stack>

      {!unlocked && (
        <Alert color="gray" variant="light" title="课表/日历为只读">
          在右上角「家长区」输入 PIN 解锁后可增删课表与事件；孩子查看不受影响。
        </Alert>
      )}
      {actionError && (
        <Alert color="red" variant="light">
          {actionError}
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
              <Group justify="space-between" align="center">
                <Text fw={600}>每周课表</Text>
                <Text size="xs" c="dimmed">
                  一节一科；改课请先删除再添加
                </Text>
              </Group>

              {slots.length === 0 ? (
                <Text size="sm" c="dimmed">
                  还没有课表。
                </Text>
              ) : (
                <Table striped withTableBorder>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>星期</Table.Th>
                      <Table.Th>节次</Table.Th>
                      <Table.Th>科目</Table.Th>
                      <Table.Th>备注</Table.Th>
                      {unlocked && <Table.Th />}
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {slots.map((slot) => (
                      <Table.Tr key={slot.id}>
                        <Table.Td>
                          {WEEKDAY_LABELS[slot.weekday - 1] ?? slot.weekday}
                        </Table.Td>
                        <Table.Td>第{slot.period}节</Table.Td>
                        <Table.Td>{slot.subject}</Table.Td>
                        <Table.Td>{slot.note ?? "—"}</Table.Td>
                        {unlocked && (
                          <Table.Td>
                            <Button
                              size="compact-xs"
                              color="red"
                              variant="light"
                              onClick={() => void removeSlot(slot.id)}
                              disabled={busy}
                            >
                              删除
                            </Button>
                          </Table.Td>
                        )}
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              )}

              {unlocked && (
                <>
                  <Divider my="xs" />
                  <Group align="flex-end" wrap="wrap">
                    <Select
                      label="星期"
                      data={WEEKDAY_OPTIONS}
                      value={weekday}
                      onChange={(value) => setWeekday(value ?? "1")}
                      w={110}
                      allowDeselect={false}
                    />
                    <NumberInput
                      label="节次"
                      value={period}
                      onChange={setPeriod}
                      min={1}
                      max={12}
                      w={100}
                    />
                    <TextInput
                      label="科目"
                      value={subject}
                      onChange={(event) => setSubject(event.currentTarget.value)}
                      placeholder="数学"
                      w={160}
                    />
                    <TextInput
                      label="备注（可选）"
                      value={note}
                      onChange={(event) => setNote(event.currentTarget.value)}
                      w={220}
                    />
                    <Button
                      onClick={() => void addSlot()}
                      loading={busy}
                      disabled={!subject.trim() || !periodValid}
                    >
                      添加课
                    </Button>
                  </Group>
                </>
              )}
            </Stack>
          </Card>

          <Card withBorder>
            <Stack gap="sm">
              <Group justify="space-between" align="center">
                <Text fw={600}>日历硬事件</Text>
                <Text size="xs" c="dimmed">
                  默认显示今天起 30 天；考试日当天会临时放宽复习上限
                </Text>
              </Group>

              {events.length === 0 ? (
                <Text size="sm" c="dimmed">
                  未来 30 天没有事件。
                </Text>
              ) : (
                <Table striped withTableBorder>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>日期</Table.Th>
                      <Table.Th>类型</Table.Th>
                      <Table.Th>标题</Table.Th>
                      <Table.Th>学科</Table.Th>
                      <Table.Th>备注</Table.Th>
                      {unlocked && <Table.Th />}
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {events.map((event) => (
                      <Table.Tr key={event.id}>
                        <Table.Td>{event.date}</Table.Td>
                        <Table.Td>
                          <Badge
                            color={KIND_COLORS[event.kind]}
                            variant="light"
                          >
                            {KIND_LABELS[event.kind]}
                          </Badge>
                        </Table.Td>
                        <Table.Td>{event.title}</Table.Td>
                        <Table.Td>{event.subject ?? "—"}</Table.Td>
                        <Table.Td>{event.note ?? "—"}</Table.Td>
                        {unlocked && (
                          <Table.Td>
                            <Button
                              size="compact-xs"
                              color="red"
                              variant="light"
                              onClick={() => void removeEvent(event.id)}
                              disabled={busy}
                            >
                              删除
                            </Button>
                          </Table.Td>
                        )}
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              )}

              {unlocked && (
                <>
                  <Divider my="xs" />
                  <Group align="flex-end" wrap="wrap">
                    <TextInput
                      label="日期"
                      type="date"
                      value={date}
                      onChange={(event) => setDate(event.currentTarget.value)}
                      w={170}
                    />
                    <Select
                      label="类型"
                      data={KIND_OPTIONS}
                      value={kind}
                      onChange={(value) => setKind(value ?? "exam")}
                      w={120}
                      allowDeselect={false}
                    />
                    <TextInput
                      label="标题"
                      value={title}
                      onChange={(event) => setTitle(event.currentTarget.value)}
                      placeholder="月考"
                      w={180}
                    />
                    <TextInput
                      label="学科（可选）"
                      value={eventSubject}
                      onChange={(event) =>
                        setEventSubject(event.currentTarget.value)
                      }
                      w={140}
                    />
                    <TextInput
                      label="备注（可选）"
                      value={eventNote}
                      onChange={(event) =>
                        setEventNote(event.currentTarget.value)
                      }
                      w={220}
                    />
                    <Button
                      onClick={() => void addEvent()}
                      loading={busy}
                      disabled={!title.trim() || !date}
                    >
                      添加事件
                    </Button>
                  </Group>
                </>
              )}
            </Stack>
          </Card>
        </>
      )}
    </Stack>
  );
}
