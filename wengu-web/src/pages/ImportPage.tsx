import {
  Alert,
  Badge,
  Button,
  Card,
  Code,
  FileButton,
  Group,
  Loader,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, errorMessage } from "../api/client";
import {
  getInboxInfo,
  importRawText,
  importTranscribe,
} from "../api/endpoints";
import type { ImportItemError, ImportResult, InboxInfo } from "../api/types";

const SUBJECTS = ["数学", "英语", "物理", "语文", "化学"];

const EXAMPLE = `{
  "channel": "agent_transcribe_v1",
  "items": [
    {
      "subject": "数学",
      "problem_text": "计算 (-3)+5",
      "student_answer": "-8",
      "standard_answer": "2",
      "error_cause_suggestion": "sign_error",
      "suggested_topic_id": "cnm_001",
      "source_ref": "校本练习 P12",
      "captured_at": "2026-10-29"
    }
  ]
}`;

function isImportItemError(value: unknown): value is ImportItemError {
  if (!value || typeof value !== "object") {
    return false;
  }
  const row = value as Record<string, unknown>;
  return (
    typeof row.index === "number" &&
    typeof row.field === "string" &&
    typeof row.reason === "string"
  );
}

function importFailure(cause: unknown): {
  message: string;
  errors: ImportItemError[];
} {
  const message = errorMessage(cause);
  if (!(cause instanceof ApiError)) {
    return { message, errors: [] };
  }
  const body = cause.detail;
  if (!body || typeof body !== "object") {
    return { message, errors: [] };
  }
  const detail = (body as { detail?: unknown }).detail;
  if (!detail || typeof detail !== "object") {
    return { message, errors: [] };
  }
  const record = detail as Record<string, unknown>;
  return {
    message: typeof record.message === "string" ? record.message : message,
    errors: Array.isArray(record.errors)
      ? record.errors.filter(isImportItemError)
      : [],
  };
}

export default function ImportPage() {
  const navigate = useNavigate();
  const [inbox, setInbox] = useState<InboxInfo | null>(null);
  const [inboxError, setInboxError] = useState<string | null>(null);

  const [rawText, setRawText] = useState("");
  const [rawFileError, setRawFileError] = useState<string | null>(null);
  const [rawSubmitting, setRawSubmitting] = useState(false);
  const [rawResult, setRawResult] = useState<ImportResult | null>(null);
  const [rawFailure, setRawFailure] = useState<{
    message: string;
    errors: ImportItemError[];
    status: number;
  } | null>(null);
  const resetFileRef = useRef<(() => void) | null>(null);

  const [subject, setSubject] = useState<string | null>("数学");
  const [problemText, setProblemText] = useState("");
  const [studentAnswer, setStudentAnswer] = useState("");
  const [standardAnswer, setStandardAnswer] = useState("");
  const [sourceRef, setSourceRef] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getInboxInfo()
      .then((response) => {
        if (active) {
          setInbox(response);
        }
      })
      .catch((cause: unknown) => {
        if (active) {
          setInboxError(errorMessage(cause));
        }
      });
    return () => {
      active = false;
    };
  }, []);

  async function submitRaw(text: string) {
    const payload = text.trim();
    if (!payload || rawSubmitting) {
      return;
    }
    setRawSubmitting(true);
    setRawFileError(null);
    setRawResult(null);
    setRawFailure(null);
    try {
      setRawResult(await importRawText(payload));
    } catch (cause) {
      setRawFailure({
        ...importFailure(cause),
        status: cause instanceof ApiError ? cause.status : 0,
      });
    } finally {
      setRawSubmitting(false);
    }
  }

  async function handleRawFile(file: File | null) {
    if (!file) {
      return;
    }
    setRawFileError(null);
    try {
      const text = await file.text();
      setRawText(text);
      await submitRaw(text);
    } catch {
      setRawFileError("读取文件失败，请重新选择 .json 文件");
    } finally {
      resetFileRef.current?.();
    }
  }

  async function handleSubmit() {
    const text = problemText.trim();
    if (!text || submitting) {
      return;
    }
    setSubmitting(true);
    setActionError(null);
    try {
      const response = await importTranscribe([
        {
          subject: subject ?? "",
          problem_text: text,
          student_answer: studentAnswer.trim(),
          standard_answer: standardAnswer.trim(),
          source_ref: sourceRef.trim(),
        },
      ]);
      setResult(response);
      setProblemText("");
      setStudentAnswer("");
      setStandardAnswer("");
      setSourceRef("");
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Stack gap="md">
      <Title order={2}>导入错题</Title>
      <Text size="sm" c="dimmed">
        v2.5：批改在卷子上完成（红笔 + 订正）。系统只接收"已批改错题"的转录
        草稿；草稿必须经核对页人工确认才入本、才排复习。
      </Text>

      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between" align="center" wrap="wrap">
            <Text fw={600}>粘贴转录 JSON</Text>
            <Badge variant="light">手机 / 平板可用</Badge>
          </Group>
          <Text size="sm" c="dimmed">
            把外部 agent 产出的整段 JSON 直接贴进来，或选择一个本地 .json
            文件。走与服务端监听目录相同的校验与去重；只生成草稿，不建错题、不自动转正。
          </Text>
          <Textarea
            label="转录 JSON"
            value={rawText}
            onChange={(event) => setRawText(event.currentTarget.value)}
            placeholder='{"channel": "agent_transcribe_v1", "items": [...]}'
            minRows={6}
            maxRows={14}
            autosize
            spellCheck={false}
            styles={{ input: { fontFamily: "monospace", fontSize: 12 } }}
          />
          <Group gap="sm" wrap="wrap">
            <FileButton
              resetRef={resetFileRef}
              onChange={(file) => void handleRawFile(file)}
              accept=".json,application/json"
            >
              {(props) => (
                <Button {...props} variant="light">
                  选择 .json 文件
                </Button>
              )}
            </FileButton>
            <Button
              onClick={() => void submitRaw(rawText)}
              loading={rawSubmitting}
              disabled={!rawText.trim()}
            >
              导入这段 JSON
            </Button>
          </Group>
          {rawFileError && (
            <Alert color="red" variant="light">
              {rawFileError}
            </Alert>
          )}
          {rawFailure && (
            <Alert
              color="red"
              variant="light"
              title={
                rawFailure.status
                  ? `导入失败（HTTP ${rawFailure.status}）`
                  : "导入失败"
              }
            >
              <Stack gap={4}>
                <Text size="sm" style={{ overflowWrap: "anywhere" }}>
                  {rawFailure.message}
                </Text>
                {rawFailure.errors.map((item) => (
                  <Text
                    key={`${item.index}-${item.field}-${item.reason}`}
                    size="xs"
                    c="red"
                    style={{ overflowWrap: "anywhere" }}
                  >
                    第 {item.index + 1} 项（index {item.index}）· {item.field}：
                    {item.reason}
                  </Text>
                ))}
              </Stack>
            </Alert>
          )}
          {rawResult && (
            <Alert
              color={
                rawResult.duplicate
                  ? "blue"
                  : rawResult.errors.length > 0
                    ? "yellow"
                    : "green"
              }
              variant="light"
              title={
                rawResult.duplicate
                  ? "重复导入已跳过"
                  : rawResult.errors.length > 0
                    ? "部分题目已导入，坏项已报告"
                    : "已生成草稿，待核对确认"
              }
            >
              <Stack gap={6}>
                <Group gap="xs">
                  <Badge variant="light">批次 #{rawResult.batch_id}</Badge>
                  <Badge variant="light">状态 {rawResult.status}</Badge>
                  <Badge variant="light">
                    duplicate {String(rawResult.duplicate)}
                  </Badge>
                  <Badge variant="light">
                    草稿 {rawResult.draft_count} 条
                  </Badge>
                  <Badge variant="light">
                    接收 {rawResult.accepted_count} 条
                  </Badge>
                  <Badge variant="light">
                    忽略未知字段 {rawResult.dropped_unknown_fields} 个
                  </Badge>
                </Group>
                {rawResult.errors.map((item) => (
                  <Text
                    key={`${item.index}-${item.field}-${item.reason}`}
                    size="xs"
                    c="red"
                    style={{ overflowWrap: "anywhere" }}
                  >
                    第 {item.index + 1} 项（index {item.index}）· {item.field}：
                    {item.reason}
                  </Text>
                ))}
                {rawResult.draft_count > 0 && (
                  <Group>
                    <Button
                      size="compact-sm"
                      onClick={() => navigate("/intake")}
                    >
                      去核对页确认
                    </Button>
                  </Group>
                )}
              </Stack>
            </Alert>
          )}
        </Stack>
      </Card>

      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between" align="center" wrap="wrap">
            <Text fw={600}>主通道：监听目录（外部 agent 写 JSON）</Text>
            {inbox && (
              <Badge variant="light">
                单批上限 {inbox.max_items} 题 /{" "}
                {Math.round(inbox.max_body_bytes / 1024 / 1024)}MB
              </Badge>
            )}
          </Group>
          {inboxError && (
            <Alert color="red" variant="light" title="读取监听目录失败">
              {inboxError}
            </Alert>
          )}
          {!inbox && !inboxError && <Loader size="xs" />}
          {inbox && (
            <>
              <Text size="sm">
                把转录好的 JSON 文件放进这个目录，后台每 2 秒扫描一次：
              </Text>
              <Code block>{inbox.path}</Code>
              <Text size="sm" c="dimmed">
                支持通道：{inbox.channels.join(" / ")}。导入只生成草稿，不判分、
                不建错题、不自动转正；坏项会跳过并逐条报告。
                看不清的字用 <Code>〔?〕</Code> 占位，核对页会强制人工处理。
              </Text>
              <Text size="sm" fw={600}>
                JSON 示例
              </Text>
              <Code block>{EXAMPLE}</Code>
            </>
          )}
        </Stack>
      </Card>

      <Card withBorder>
        <Stack gap="sm">
          <Text fw={600}>后手：家长手填一条</Text>
          <Text size="xs" c="dimmed">
            没有外部 agent 时，手填最小字段也能生成草稿；正答取卷面订正后的答案。
          </Text>
          <Group grow align="flex-start" wrap="wrap">
            <Select
              label="学科"
              data={SUBJECTS}
              value={subject}
              onChange={setSubject}
              clearable
              placeholder="选择学科"
            />
            <TextInput
              label="出处（可选）"
              value={sourceRef}
              onChange={(event) => setSourceRef(event.currentTarget.value)}
              placeholder="例如：校本练习 P12"
              maxLength={200}
            />
          </Group>
          <Textarea
            label="题目（卷面原文）"
            required
            value={problemText}
            onChange={(event) => setProblemText(event.currentTarget.value)}
            placeholder="题目内容；看不清的字用〔?〕占位"
            minRows={3}
            autosize
            maxLength={2000}
          />
          <Group grow align="flex-start" wrap="wrap">
            <TextInput
              label="错答（被红笔判错）"
              value={studentAnswer}
              onChange={(event) => setStudentAnswer(event.currentTarget.value)}
              maxLength={500}
            />
            <TextInput
              label="正答（卷面订正）"
              value={standardAnswer}
              onChange={(event) => setStandardAnswer(event.currentTarget.value)}
              maxLength={500}
            />
          </Group>
          {actionError && (
            <Alert color="red" variant="light">
              {actionError}
            </Alert>
          )}
          {result && (
            <Alert
              color={result.duplicate ? "blue" : "green"}
              variant="light"
              title={
                result.duplicate ? "重复导入：已跳过" : "已生成草稿，待核对确认"
              }
            >
              <Stack gap={4}>
                <Text size="sm">
                  批次 #{result.batch_id} · 草稿 {result.draft_count} 条 · 跳过坏项{" "}
                  {result.errors.length} 条
                </Text>
                {result.errors.map((item) => (
                  <Text key={`${item.index}-${item.field}`} size="xs" c="red">
                    第 {item.index + 1} 项 · {item.field}：{item.reason}
                  </Text>
                ))}
                {result.draft_count > 0 && (
                  <Group>
                    <Button
                      size="compact-sm"
                      onClick={() => navigate("/intake")}
                    >
                      去核对页确认
                    </Button>
                  </Group>
                )}
              </Stack>
            </Alert>
          )}
          <Group>
            <Button
              onClick={() => void handleSubmit()}
              loading={submitting}
              disabled={!problemText.trim()}
            >
              生成草稿
            </Button>
            <Text size="xs" c="dimmed">
              手填只生成草稿；确认入本在核对页完成。
            </Text>
          </Group>
        </Stack>
      </Card>
    </Stack>
  );
}
