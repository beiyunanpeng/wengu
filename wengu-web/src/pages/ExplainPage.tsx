import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  List,
  Select,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { errorMessage } from "../api/client";
import {
  createExplanation,
  getMistake,
  listMistakes,
  recordExplanationAttempt,
} from "../api/endpoints";
import { readExtractionContext } from "../api/explainContext";
import type {
  ExplainMode,
  ExplainSourceKind,
  ExplanationResponse,
  MistakeDetail,
} from "../api/types";
import MathText from "../components/MathText";

const MODE_OPTIONS: { value: ExplainMode; label: string }[] = [
  { value: "auto", label: "自动（按错因选择引导或讲解）" },
  { value: "guide", label: "引导（分步提示）" },
  { value: "full", label: "完整讲解" },
];

const HINT_OPTIONS = [
  { value: "1", label: "提示 1（轻）" },
  { value: "2", label: "提示 2（中）" },
  { value: "3", label: "提示 3（强）" },
];

function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function sourceLabel(kind: ExplainSourceKind | null): string {
  if (kind === "mistake") {
    return "错题订正";
  }
  if (kind === "problem_extraction") {
    return "拍照答疑";
  }
  return "讲解";
}

export default function ExplainPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const rawKind = searchParams.get("source_kind");
  const rawId = searchParams.get("source_id");
  const sourceKind: ExplainSourceKind | null =
    rawKind === "mistake" || rawKind === "problem_extraction"
      ? rawKind
      : null;
  const sourceId =
    rawId && /^\d+$/.test(rawId) ? Number(rawId) : null;

  const [problemText, setProblemText] = useState<string | null>(null);
  const [studentAnswer, setStudentAnswer] = useState<string | null>(null);
  const [contextError, setContextError] = useState<string | null>(null);
  const [contextLoading, setContextLoading] = useState(false);
  const [recent, setRecent] = useState<MistakeDetail[]>([]);

  const [mode, setMode] = useState<ExplainMode>("auto");
  const [hintLevel, setHintLevel] = useState(1);
  const [result, setResult] = useState<ExplanationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [attemptBusy, setAttemptBusy] = useState(false);
  const requestIdRef = useRef<string | null>(null);
  const attemptIdRef = useRef<string>(newId());

  useEffect(() => {
    if (!sourceKind || sourceId === null) {
      return;
    }
    setResult(null);
    setError(null);
    setContextError(null);
    requestIdRef.current = null;
    if (sourceKind === "mistake") {
      let active = true;
      setContextLoading(true);
      getMistake(sourceId)
        .then((detail) => {
          if (!active) {
            return;
          }
          setProblemText(detail.problem_text);
          setStudentAnswer(detail.student_answer);
        })
        .catch((cause: unknown) => {
          if (active) {
            setContextError(errorMessage(cause));
          }
        })
        .finally(() => {
          if (active) {
            setContextLoading(false);
          }
        });
      return () => {
        active = false;
      };
    }
    const context = readExtractionContext(sourceId);
    if (context) {
      setProblemText(context.problemText);
      setStudentAnswer(context.studentAnswer);
    } else {
      setProblemText(null);
      setStudentAnswer(null);
      setContextError(
        "刷新后没有恢复这道采集题的原文；仍可生成讲解，从采集页进入可显示原文。",
      );
    }
    return;
  }, [sourceKind, sourceId]);

  useEffect(() => {
    if (sourceKind && sourceId !== null) {
      return;
    }
    let active = true;
    listMistakes({ limit: 50 })
      .then((response) => {
        if (active) {
          setRecent(response.items);
        }
      })
      .catch(() => {
        // 无参数入口只是兜底选择器，列表失败不阻塞手动带参进入
      });
    return () => {
      active = false;
    };
  }, [sourceKind, sourceId]);

  useEffect(() => {
    if (!loading) {
      setElapsed(0);
      return;
    }
    const startedAt = Date.now();
    setElapsed(0);
    const timer = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    }, 500);
    return () => clearInterval(timer);
  }, [loading]);

  async function generate(nextMode?: ExplainMode, nextHint?: number) {
    if (!sourceKind || sourceId === null) {
      return;
    }
    const useMode = nextMode ?? mode;
    const useHint = nextHint ?? hintLevel;
    setLoading(true);
    setError(null);
    try {
      const requestId = requestIdRef.current ?? newId();
      requestIdRef.current = requestId;
      const response = await createExplanation({
        source_kind: sourceKind,
        source_id: sourceId,
        mode: useMode,
        hint_level: useHint,
        request_id: requestId,
      });
      setResult(response);
      setMode(useMode);
      setHintLevel(useHint);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setLoading(false);
    }
  }

  function generateFresh() {
    requestIdRef.current = null;
    void generate();
  }

  async function markAttempted() {
    if (!result || !sourceKind || sourceId === null || attemptBusy) {
      return;
    }
    setAttemptBusy(true);
    setError(null);
    try {
      await recordExplanationAttempt({
        source_kind: sourceKind,
        source_id: sourceId,
        attempt_id: attemptIdRef.current,
        mode: result.mode,
        hint_level: result.hint_level ?? 1,
      });
      requestIdRef.current = null;
      await generate("full", result.hint_level ?? hintLevel);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setAttemptBusy(false);
    }
  }

  function nextHint() {
    if (!result?.next_hint_level) {
      return;
    }
    requestIdRef.current = null;
    void generate("guide", result.next_hint_level);
  }

  if (!sourceKind || sourceId === null) {
    return (
      <Stack gap="md">
        <Title order={2}>讲解</Title>
        <Alert color="blue" variant="light">
          从错题本或采集页进入会自动带上题目；也可以先选一道错题。
        </Alert>
        <Select
          label="选择错题"
          placeholder="选择一道错题开始讲解"
          searchable
          data={recent.map((item) => ({
            value: String(item.id),
            label: `#${item.id} ${(item.problem_text ?? "（无题目文本）").slice(0, 40)}`,
          }))}
          onChange={(value) => {
            if (value) {
              navigate(`/explain?source_kind=mistake&source_id=${value}`);
            }
          }}
          nothingFoundMessage="还没有错题，先去采集页录一道"
        />
        <Group>
          <Button variant="light" onClick={() => navigate("/mistakes")}>
            去错题本
          </Button>
          <Button variant="subtle" onClick={() => navigate("/capture")}>
            去采集
          </Button>
        </Group>
      </Stack>
    );
  }

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center">
        <Group gap="xs">
          <Title order={2}>讲解</Title>
          <Badge variant="light">{sourceLabel(sourceKind)}</Badge>
        </Group>
        <Group gap="xs">
          <Button size="compact-sm" variant="subtle" onClick={() => navigate("/mistakes")}>
            错题本
          </Button>
          <Button size="compact-sm" variant="subtle" onClick={() => navigate("/review")}>
            复习
          </Button>
        </Group>
      </Group>

      {contextLoading ? (
        <Group justify="center" py="md">
          <Loader size="sm" />
        </Group>
      ) : (
        <Card withBorder>
          <Stack gap="sm">
            <Text size="sm" fw={600}>
              题目
            </Text>
            <MathText text={problemText || "（未恢复题目文本）"} />
            <Text size="sm" fw={600}>
              孩子作答
            </Text>
            <MathText text={studentAnswer || "（空）"} />
            {contextError && (
              <Alert color="yellow" variant="light">
                {contextError}
              </Alert>
            )}
          </Stack>
        </Card>
      )}

      <Card withBorder>
        <Stack gap="sm">
          <Group align="flex-end" wrap="wrap">
            <Select
              label="模式"
              data={MODE_OPTIONS}
              value={mode}
              onChange={(value) => {
                if (value) {
                  setMode(value as ExplainMode);
                  requestIdRef.current = null;
                }
              }}
              allowDeselect={false}
              style={{ flex: "1 1 260px" }}
            />
            <Select
              label="提示级别"
              data={HINT_OPTIONS}
              value={String(hintLevel)}
              onChange={(value) => {
                if (value) {
                  setHintLevel(Number(value));
                  requestIdRef.current = null;
                }
              }}
              allowDeselect={false}
              style={{ flex: "1 1 160px" }}
            />
          </Group>
          <Text size="xs" c="dimmed">
            引导不直接甩答案；完整讲解需要先动手尝试，答案不会一上来就给出。
          </Text>
          <Group>
            <Button
              onClick={() => (result ? generateFresh() : void generate())}
              loading={loading}
              disabled={loading || contextLoading}
            >
              {result ? "重新生成" : "生成讲解"}
            </Button>
            {result && !loading && (
              <Button variant="light" onClick={() => void generate()}>
                重试上一次
              </Button>
            )}
          </Group>
          {loading && (
            <Alert
              color="blue"
              variant="light"
              icon={<Loader size="sm" />}
              title="正在生成讲解"
            >
              已等待 {elapsed} 秒。模型讲解通常需要 20–40 秒。
            </Alert>
          )}
          {error && (
            <Alert color="red" variant="light" title="讲解失败">
              <Stack gap="xs">
                <Text size="sm">{error}</Text>
                <Group>
                  <Button size="compact-sm" onClick={() => void generate()} disabled={loading}>
                    重试
                  </Button>
                </Group>
              </Stack>
            </Alert>
          )}
        </Stack>
      </Card>

      {result && (
        <Card withBorder>
          <Stack gap="md">
            <Group gap="xs" wrap="wrap">
              <Badge variant="light">{result.strategy_label}</Badge>
              <Badge variant="outline">
                {result.mode === "guide" ? "引导" : "完整讲解"}
              </Badge>
              {result.hint_level !== null && (
                <Badge variant="outline">提示 {result.hint_level}</Badge>
              )}
              {result.attempted && (
                <Badge color="green" variant="light">
                  已记录动手尝试
                </Badge>
              )}
            </Group>

            <div>
              <Text size="sm" fw={600} mb={4}>
                定位
              </Text>
              <MathText text={result.explanation.focus} />
            </div>

            <div>
              <Text size="sm" fw={600} mb={4}>
                步骤
              </Text>
              <List type="ordered" spacing="xs">
                {result.explanation.steps.map((step, index) => (
                  <List.Item key={index}>
                    <MathText text={step} />
                  </List.Item>
                ))}
              </List>
            </div>

            <div>
              <Text size="sm" fw={600} mb={4}>
                巩固
              </Text>
              <MathText text={result.explanation.consolidation} />
            </div>

            {result.soft_gate && !result.attempted && (
              <Alert color="yellow" variant="light" title="先自己试一下">
                <Stack gap="xs">
                  <Text size="sm">
                    完整答案还在门槛后面。先在纸上写一步，或直接记录你已经尝试过，再查看完整讲解。
                  </Text>
                  <Group>
                    <Button
                      size="compact-sm"
                      onClick={() => void markAttempted()}
                      loading={attemptBusy}
                      disabled={loading}
                    >
                      我试过了，查看完整讲解
                    </Button>
                  </Group>
                </Stack>
              </Alert>
            )}

            {result.mode === "guide" && result.next_hint_level !== null && (
              <Group>
                <Button variant="light" onClick={nextHint} disabled={loading}>
                  再给一点提示
                </Button>
              </Group>
            )}

            {result.answer_shown &&
            result.explanation.answer &&
            !(result.soft_gate && !result.attempted) ? (
              <Card withBorder bg="green.0">
                <Text size="sm" fw={600} mb={4}>
                  完整答案
                </Text>
                <MathText text={result.explanation.answer} />
              </Card>
            ) : (
              <Text size="sm" c="dimmed">
                完整答案暂未展示；可以继续看引导，或先动手尝试一次。
              </Text>
            )}

            {result.leak_flags.length > 0 && (
              <Text size="xs" c="orange">
                质量标记：{result.leak_flags.join("、")}
              </Text>
            )}

            <Text size="xs" c="dimmed">
              {result.meta.provider} / {result.meta.model} · 延迟{" "}
              {result.meta.latency_ms} ms
              {result.meta.cache_hit ? " · 缓存命中" : ""}
            </Text>
          </Stack>
        </Card>
      )}
    </Stack>
  );
}
