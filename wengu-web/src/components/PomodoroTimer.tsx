import {
  Alert,
  Button,
  Group,
  NumberInput,
  Progress,
  Stack,
  Text,
} from "@mantine/core";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, errorMessage } from "../api/client";
import {
  abandonPomodoro,
  completePomodoro,
  getActivePomodoro,
  startPomodoro,
} from "../api/endpoints";
import type { PomodoroSession } from "../api/types";
import { toISODate } from "../lib/dates";
import {
  DEFAULT_FOCUS_MINUTES,
  MAX_FOCUS_MINUTES,
  MIN_FOCUS_MINUTES,
  focusMinutes,
} from "../lib/pomodoro";

type Phase = "loading" | "idle" | "running" | "done";

function format(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

/**
 * P2-2b 番茄计时器：进行中轮次存在服务端，挂载时读回续走，刷新 / 切页 /
 * 换设备都接着走。完成才写 `pomodoro_completed` 事实，放弃只翻轮次状态、
 * 不打点；不做暂停、不自动开始下一个、不做后台计时或通知。
 */
export default function PomodoroTimer({
  mistakeId,
  onRecorded,
}: {
  mistakeId?: number | null;
  onRecorded?: () => void;
}) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [session, setSession] = useState<PomodoroSession | null>(null);
  const [remaining, setRemaining] = useState(0);
  const [planned, setPlanned] = useState<number | string>(DEFAULT_FOCUS_MINUTES);
  const [recordedMinutes, setRecordedMinutes] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 服务端读数是唯一真源；这里只把剩余秒数落到本地时钟，供两次读数之间插值。
  const endsAtRef = useRef<number | null>(null);
  const autoSubmitRef = useRef(false);
  const submittingRef = useRef(false);

  const adopt = useCallback((view: PomodoroSession) => {
    setSession(view);
    setRemaining(view.remaining_seconds);
    endsAtRef.current = Date.now() + view.remaining_seconds * 1000;
    // 续走时已经到点的轮次不自动打点：离开页面那段时间不能算作专注。
    autoSubmitRef.current = view.remaining_seconds > 0;
    setRecordedMinutes(null);
    setError(null);
    setPhase("running");
  }, []);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const response = await getActivePomodoro();
        if (!alive) {
          return;
        }
        if (response.session) {
          adopt(response.session);
        } else {
          setPhase("idle");
        }
      } catch (cause) {
        if (!alive) {
          return;
        }
        setError(errorMessage(cause));
        setPhase("idle");
      }
    })();
    return () => {
      alive = false;
    };
  }, [adopt]);

  useEffect(() => {
    if (phase !== "running") {
      return;
    }
    const timer = window.setInterval(() => {
      const endsAt = endsAtRef.current;
      if (endsAt === null) {
        return;
      }
      setRemaining(Math.max(0, Math.round((endsAt - Date.now()) / 1000)));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [phase]);

  useEffect(() => {
    if (phase === "running" && remaining === 0 && autoSubmitRef.current) {
      autoSubmitRef.current = false;
      void submit();
    }
    // submit 只读当前渲染的 session/remaining 快照，不需要进依赖数组
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, remaining]);

  async function start() {
    const minutes = typeof planned === "number" ? planned : Number(planned);
    if (
      !Number.isInteger(minutes) ||
      minutes < MIN_FOCUS_MINUTES ||
      minutes > MAX_FOCUS_MINUTES
    ) {
      setError(
        `专注时长请填 ${MIN_FOCUS_MINUTES}–${MAX_FOCUS_MINUTES} 的整数分钟`,
      );
      return;
    }
    setBusy(true);
    setError(null);
    try {
      adopt(
        await startPomodoro({
          planned_minutes: minutes,
          mistake_id: mistakeId ?? null,
        }),
      );
    } catch (cause) {
      // 另一台设备已经开了轮次：接着走那一轮，而不是把人卡在报错上。
      const active =
        cause instanceof ApiError && cause.status === 409
          ? await getActivePomodoro().catch(() => null)
          : null;
      if (active?.session) {
        adopt(active.session);
      } else {
        setError(errorMessage(cause));
      }
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    const current = session;
    if (!current || submittingRef.current) {
      return;
    }
    submittingRef.current = true;
    setBusy(true);
    try {
      const response = await completePomodoro(current.id, {
        duration_minutes: focusMinutes(current.planned_minutes, remaining),
        completed_on: toISODate(new Date()),
      });
      setRecordedMinutes(response.duration_minutes);
      setSession(null);
      endsAtRef.current = null;
      setPhase("done");
      setError(null);
      onRecorded?.();
    } catch (cause) {
      setError(errorMessage(cause));
      autoSubmitRef.current = false;
    } finally {
      submittingRef.current = false;
      setBusy(false);
    }
  }

  async function abandon() {
    const current = session;
    if (!current) {
      return;
    }
    setBusy(true);
    try {
      await abandonPomodoro(current.id);
      setSession(null);
      endsAtRef.current = null;
      autoSubmitRef.current = false;
      setRemaining(0);
      setPhase("idle");
      setError(null);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  const totalSeconds = (session?.planned_minutes ?? DEFAULT_FOCUS_MINUTES) * 60;

  return (
    <Stack gap={6}>
      {phase === "loading" && (
        <Text size="xs" c="dimmed">
          正在读取进行中的专注轮次…
        </Text>
      )}

      {phase === "running" && session && (
        <Group gap="sm" wrap="wrap">
          <Text fw={700} ff="monospace" size="lg" w={64}>
            {format(remaining)}
          </Text>
          <Progress
            value={((totalSeconds - remaining) / totalSeconds) * 100}
            size="sm"
            style={{ flex: 1, minWidth: 80 }}
            aria-label={`专注剩余 ${format(remaining)}`}
          />
          <Group gap={4} wrap="nowrap">
            <Button
              size="compact-sm"
              onClick={() => void submit()}
              loading={busy}
            >
              完成
            </Button>
            <Button
              size="compact-sm"
              variant="subtle"
              color="gray"
              onClick={() => void abandon()}
              disabled={busy}
            >
              放弃
            </Button>
          </Group>
        </Group>
      )}

      {(phase === "idle" || phase === "done") && (
        <Group gap="sm" wrap="wrap">
          <NumberInput
            size="xs"
            w={92}
            min={MIN_FOCUS_MINUTES}
            max={MAX_FOCUS_MINUTES}
            step={5}
            value={planned}
            onChange={setPlanned}
            disabled={busy}
            aria-label="专注时长（分钟）"
            suffix=" 分"
          />
          <Button
            size="compact-sm"
            variant="light"
            onClick={() => void start()}
            loading={busy}
          >
            {phase === "done" ? "再专注一个" : "开始专注"}
          </Button>
          <Text size="xs" c="dimmed">
            {phase === "done" && recordedMinutes !== null
              ? `已记录 ${recordedMinutes} 分钟番茄`
              : `可选 ${MIN_FOCUS_MINUTES}–${MAX_FOCUS_MINUTES} 分钟；放弃不打点`}
          </Text>
        </Group>
      )}

      <Text size="xs" c="dimmed">
        {phase === "running" && remaining === 0
          ? "时间已到，点「完成」才打点。"
          : "轮次存在服务端，刷新或换设备都接着走；不自动开始下一个，也不计入掌握度或打卡。"}
      </Text>
      {error && (
        <Alert color="red" variant="light" py={4}>
          番茄操作失败：{error}
        </Alert>
      )}
    </Stack>
  );
}
