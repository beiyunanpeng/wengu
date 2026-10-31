import { Alert, Button, Group, Progress, Stack, Text } from "@mantine/core";
import { useEffect, useRef, useState } from "react";

import { errorMessage } from "../api/client";
import { recordPomodoro } from "../api/endpoints";
import { toISODate } from "../lib/dates";

const TOTAL_MINUTES = 25;
const TOTAL_SECONDS = TOTAL_MINUTES * 60;

type Phase = "idle" | "running" | "done";

function format(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

/**
 * P2-2 番茄计时器：纯前端 25 分钟倒计时，完成才打点。
 * 取消 / 刷新 / 关页都不产生事实；不自动开始下一个，也不做后台计时或通知。
 */
export default function PomodoroTimer({
  mistakeId,
  onRecorded,
}: {
  mistakeId?: number | null;
  onRecorded?: () => void;
}) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [remaining, setRemaining] = useState(TOTAL_SECONDS);
  const [recordedMinutes, setRecordedMinutes] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const startedAtRef = useRef<number | null>(null);
  const submittingRef = useRef(false);

  useEffect(() => {
    if (phase !== "running") {
      return;
    }
    const timer = window.setInterval(() => {
      const started = startedAtRef.current ?? Date.now();
      const left = Math.max(
        0,
        TOTAL_SECONDS - Math.floor((Date.now() - started) / 1000),
      );
      setRemaining(left);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [phase]);

  useEffect(() => {
    if (phase === "running" && remaining === 0) {
      void submit(TOTAL_MINUTES);
    }
    // submit 只依赖 ref/state 快照，不需要进依赖数组
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, remaining]);

  function start() {
    startedAtRef.current = Date.now();
    setRemaining(TOTAL_SECONDS);
    setRecordedMinutes(null);
    setError(null);
    setPhase("running");
  }

  function cancel() {
    startedAtRef.current = null;
    setRemaining(TOTAL_SECONDS);
    setError(null);
    setPhase("idle");
  }

  async function submit(minutes: number) {
    if (submittingRef.current) {
      return;
    }
    submittingRef.current = true;
    setBusy(true);
    try {
      const startedAt = new Date(startedAtRef.current ?? Date.now());
      const response = await recordPomodoro({
        mistake_id: mistakeId ?? null,
        duration_minutes: minutes,
        started_at: startedAt.toISOString(),
        completed_on: toISODate(new Date()),
      });
      setRecordedMinutes(response.duration_minutes);
      setPhase("done");
      setError(null);
      onRecorded?.();
    } catch (cause) {
      setError(errorMessage(cause));
      setPhase("idle");
      setRemaining(TOTAL_SECONDS);
    } finally {
      submittingRef.current = false;
      setBusy(false);
    }
  }

  function finishEarly() {
    const started = startedAtRef.current ?? Date.now();
    const elapsed = Math.round((Date.now() - started) / 60000);
    void submit(Math.min(TOTAL_MINUTES, Math.max(1, elapsed)));
  }

  return (
    <Stack gap={6}>
      {phase === "running" ? (
        <Group gap="sm" wrap="nowrap">
          <Text fw={700} ff="monospace" size="lg" w={64}>
            {format(remaining)}
          </Text>
          <Progress
            value={((TOTAL_SECONDS - remaining) / TOTAL_SECONDS) * 100}
            size="sm"
            style={{ flex: 1 }}
            aria-label={`专注剩余 ${format(remaining)}`}
          />
          <Button size="compact-sm" onClick={finishEarly} loading={busy}>
            完成
          </Button>
          <Button
            size="compact-sm"
            variant="subtle"
            color="gray"
            onClick={cancel}
            disabled={busy}
          >
            取消
          </Button>
        </Group>
      ) : (
        <Group gap="sm" wrap="wrap">
          <Button size="compact-sm" variant="light" onClick={start}>
            {phase === "done" ? "再专注一个" : "开始专注"}
          </Button>
          <Text size="xs" c="dimmed">
            {phase === "done" && recordedMinutes !== null
              ? `已记录 ${recordedMinutes} 分钟番茄`
              : "25 分钟倒计时；取消或刷新页面都不打点"}
          </Text>
        </Group>
      )}
      <Text size="xs" c="dimmed">
        计时只在这个页面，不会后台运行、不会自动开始下一个，也不计入掌握度或打卡。
      </Text>
      {error && (
        <Alert color="red" variant="light" py={4}>
          番茄打点失败：{error}
        </Alert>
      )}
    </Stack>
  );
}
