import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Image,
  List,
  Loader,
  Select,
  Stack,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { errorMessage } from "../api/client";
import {
  createGrading,
  extractCapture,
  listExtractions,
  QUESTION_TYPE_LABELS,
  sliceCapture,
  uploadCapture,
} from "../api/endpoints";
import { saveExtractionContext } from "../api/explainContext";
import type {
  ExtractionBatch,
  ExtractionInfo,
  GateStatus,
  QuestionType,
} from "../api/types";
import MathText from "../components/MathText";

type Phase =
  | "idle"
  | "restoring"
  | "uploading"
  | "slicing"
  | "extracting"
  | "ready"
  | "error";

const QUESTION_TYPES = (Object.keys(QUESTION_TYPE_LABELS) as QuestionType[]).map(
  (value) => ({ value, label: QUESTION_TYPE_LABELS[value] }),
);

const GATE_INFO: Record<GateStatus, { color: string; label: string }> = {
  ready_for_grading: { color: "green", label: "可批改" },
  manual_review: { color: "yellow", label: "需人工复核" },
  figure_dependent: { color: "red", label: "依赖图形" },
};

const REASON_LABELS: Record<string, string> = {
  placeholder: "题目含〔?〕占位",
  student_answer_empty: "孩子作答为空",
  problem_incomplete: "题目识别不完整",
  problem_empty: "未识别到题目",
  figure_dependent: "题目依赖图形",
  extraction_gate: "提取质量闸门未通过",
};

const PHASE_TITLES: Partial<Record<Phase, string>> = {
  restoring: "读取已有识别结果",
  uploading: "上传照片",
  slicing: "本地切题（不联网）",
  extracting: "识别题目（模型调用，通常每题 15–40 秒）",
};

function reasonLabel(reason: string): string {
  return REASON_LABELS[reason] ?? reason;
}

function ExtractionCard({ extraction }: { extraction: ExtractionInfo }) {
  const navigate = useNavigate();
  const [questionType, setQuestionType] = useState<QuestionType>("objective");
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const gate = GATE_INFO[extraction.gate_status];
  const ready = extraction.gate_status === "ready_for_grading";
  const needsAnswer = questionType !== "open";

  async function submit() {
    if (!ready || busy) {
      return;
    }
    if (needsAnswer && !answer.trim()) {
      setError("请先填写标准答案/参考答案，再提交批改");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await createGrading({
        source_kind: "problem_extraction",
        source_id: extraction.id,
        question_type: questionType,
        answer: needsAnswer ? answer.trim() : null,
        samples: 1,
      });
      if (response.route === "explanation") {
        saveExtractionContext(extraction.id, {
          problemText: extraction.problem_text,
          studentAnswer: extraction.student_answer,
        });
        navigate(
          `/explain?source_kind=problem_extraction&source_id=${extraction.id}`,
        );
        return;
      }
      if (response.grading) {
        navigate(`/grading/${response.grading.id}`);
      } else {
        setError("批改没有返回结果，请重试");
      }
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card withBorder>
      <Stack gap="sm">
        <Group justify="space-between">
          <Badge variant="light">第 {extraction.seq} 题</Badge>
          <Group gap="xs">
            {extraction.confidence !== null && (
              <Text size="xs" c="dimmed">
                置信度 {Math.round(extraction.confidence * 100)}%
              </Text>
            )}
            <Badge color={gate.color} variant="light">
              {gate.label}
            </Badge>
          </Group>
        </Group>

        <div>
          <Text size="sm" fw={600} mb={4}>
            识别题目
          </Text>
          <MathText text={extraction.problem_text} />
        </div>
        <div>
          <Text size="sm" fw={600} mb={4}>
            孩子作答
          </Text>
          <MathText text={extraction.student_answer || "（空）"} />
        </div>

        {extraction.review_reasons.length > 0 && (
          <Alert color="yellow" variant="light" title="提取闸门提示">
            <List size="sm" spacing={2}>
              {extraction.review_reasons.map((reason) => (
                <List.Item key={reason}>{reasonLabel(reason)}</List.Item>
              ))}
            </List>
          </Alert>
        )}
        {extraction.figure_keywords.length > 0 && (
          <Text size="sm" c="dimmed">
            图形关键词：{extraction.figure_keywords.join("、")}
          </Text>
        )}

        {ready ? (
          <Stack gap="sm">
            <Select
              label="题型"
              data={QUESTION_TYPES}
              value={questionType}
              onChange={(value) => {
                if (value) {
                  setQuestionType(value as QuestionType);
                  setError(null);
                }
              }}
              allowDeselect={false}
            />
            {needsAnswer && (
              <Textarea
                label={
                  questionType === "objective"
                    ? "标准答案（必填）"
                    : "参考答案（必填）"
                }
                description={
                  questionType === "objective"
                    ? "客观题由代码做规范化比对，模型不参与判对错"
                    : "过程题只给保守初判，最终以你的确认为准"
                }
                value={answer}
                onChange={(event) => setAnswer(event.currentTarget.value)}
                autosize
                minRows={1}
                maxRows={4}
                placeholder={
                  questionType === "objective" ? "例如：2 或 1/2" : "例如：x=2"
                }
              />
            )}
            <Button onClick={submit} loading={busy}>
              {questionType === "open" ? "去讲解" : "提交批改"}
            </Button>
            {error && (
              <Alert color="red" variant="light">
                {error}
              </Alert>
            )}
          </Stack>
        ) : (
          <Alert color="yellow" variant="light">
            这道题未通过提取质量闸门，暂不进入判分；请核对原图后重新拍照或改用人工处理。
          </Alert>
        )}
      </Stack>
    </Card>
  );
}

export default function CapturePage() {
  const navigate = useNavigate();
  const params = useParams();
  const routeCaptureId = params.captureId ? Number(params.captureId) : null;

  const [captureId, setCaptureId] = useState<number | null>(routeCaptureId);
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>(routeCaptureId ? "restoring" : "idle");
  const [batch, setBatch] = useState<ExtractionBatch | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const busy =
    phase === "restoring" ||
    phase === "uploading" ||
    phase === "slicing" ||
    phase === "extracting";

  useEffect(() => {
    if (!previewUrl) {
      return;
    }
    return () => URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  useEffect(() => {
    if (!busy) {
      setElapsed(0);
      return;
    }
    const startedAt = Date.now();
    setElapsed(0);
    const timer = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    }, 500);
    return () => clearInterval(timer);
  }, [busy, phase]);

  useEffect(() => {
    if (routeCaptureId === null || Number.isNaN(routeCaptureId)) {
      return;
    }
    let active = true;
    setCaptureId(routeCaptureId);
    setPhase("restoring");
    listExtractions(routeCaptureId)
      .then((result) => {
        if (!active) {
          return;
        }
        setBatch(result);
        setPhase("ready");
      })
      .catch((cause: unknown) => {
        if (!active) {
          return;
        }
        setError(errorMessage(cause));
        setPhase("error");
      });
    return () => {
      active = false;
    };
  }, [routeCaptureId]);

  function pickFile(next: File | null) {
    setError(null);
    if (!next) {
      setFile(null);
      setPreviewUrl(null);
      return;
    }
    if (next.size > 20 * 1024 * 1024) {
      setFile(null);
      setPreviewUrl(null);
      setError("照片超过 20MB 上限，请压缩或重新拍摄");
      return;
    }
    if (
      next.type &&
      !["image/jpeg", "image/png", "image/webp"].includes(next.type)
    ) {
      setFile(null);
      setPreviewUrl(null);
      setError("仅支持 JPEG / PNG / WebP 照片");
      return;
    }
    setFile(next);
    setPreviewUrl(URL.createObjectURL(next));
  }

  async function runExtraction(id: number) {
    setPhase("extracting");
    setError(null);
    try {
      const result = await extractCapture(id);
      setBatch(result);
      setPhase("ready");
      if (result.failed_count > 0) {
        setError(`${result.failed_count} 题提取失败，可点“重试提取”补齐`);
      }
    } catch (cause) {
      setError(errorMessage(cause));
      setPhase("error");
    }
  }

  async function runPipeline(id: number) {
    setNotice(null);
    setPhase("slicing");
    try {
      const sliced = await sliceCapture(id);
      if (sliced.item_count === 0) {
        setNotice("未识别到题号锚点，按整页提取");
      }
    } catch (cause) {
      setNotice(`自动切题未完成（${errorMessage(cause)}），按整页提取`);
    }
    await runExtraction(id);
  }

  async function handleUpload() {
    if (!file || busy) {
      return;
    }
    setError(null);
    setNotice(null);
    setBatch(null);
    setPhase("uploading");
    let id: number;
    try {
      const created = await uploadCapture(file);
      id = created.capture_id;
      setCaptureId(id);
    } catch (cause) {
      setError(errorMessage(cause));
      setPhase("error");
      return;
    }
    try {
      await runPipeline(id);
    } finally {
      navigate(`/capture/${id}`, { replace: true });
    }
  }

  function reset() {
    setFile(null);
    setPreviewUrl(null);
    setBatch(null);
    setCaptureId(null);
    setError(null);
    setNotice(null);
    setPhase("idle");
    navigate("/capture");
  }

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center">
        <Title order={2}>采集</Title>
        <Text size="xs" c="dimmed">
          照片只在本机与自托管后端之间传输
        </Text>
      </Group>

      <Card withBorder>
        <Stack gap="sm">
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            capture="environment"
            style={{ display: "none" }}
            onChange={(event) => {
              const next = event.currentTarget.files?.[0] ?? null;
              event.currentTarget.value = "";
              pickFile(next);
            }}
          />
          {previewUrl && (
            <Image
              src={previewUrl}
              alt="待上传照片预览"
              mah={360}
              fit="contain"
            />
          )}
          <Group>
            <Button
              variant="light"
              onClick={() => fileInputRef.current?.click()}
              disabled={busy}
            >
              {file ? "重新选择照片" : "拍照 / 选择照片"}
            </Button>
            {file && (
              <Button
                onClick={handleUpload}
                loading={phase === "uploading"}
                disabled={busy}
              >
                上传并识别
              </Button>
            )}
            {(batch || captureId) && (
              <Button variant="subtle" onClick={reset} disabled={busy}>
                重新开始
              </Button>
            )}
          </Group>
          {file && (
            <Text size="sm" c="dimmed">
              {file.name} · {(file.size / 1024 / 1024).toFixed(1)} MB
            </Text>
          )}
        </Stack>
      </Card>

      {busy && (
        <Alert
          color="blue"
          variant="light"
          icon={<Loader size="sm" />}
          title={PHASE_TITLES[phase]}
        >
          已等待 {elapsed} 秒。模型识别较慢时可以继续等待，失败后可重试。
        </Alert>
      )}
      {notice && (
        <Alert color="yellow" variant="light">
          {notice}
        </Alert>
      )}
      {error && (
        <Alert color="red" variant="light" title="处理失败">
          <Stack gap="xs">
            <Text size="sm">{error}</Text>
            <Group>
              {captureId !== null && (
                <Button
                  size="compact-sm"
                  variant="light"
                  onClick={() => runExtraction(captureId)}
                  disabled={busy}
                >
                  重试提取
                </Button>
              )}
              <Button size="compact-sm" variant="subtle" onClick={reset}>
                重新上传
              </Button>
            </Group>
          </Stack>
        </Alert>
      )}

      {batch && batch.results.length === 0 && !busy && (
        <Alert color="yellow" variant="light" title="没有识别结果">
          <Stack gap="xs">
            <Text size="sm">这张照片还没有可用的识别结果，可以重试提取。</Text>
            {captureId !== null && (
              <Button
                size="compact-sm"
                onClick={() => runExtraction(captureId)}
              >
                开始提取
              </Button>
            )}
          </Stack>
        </Alert>
      )}

      {batch && batch.results.length > 0 && (
        <Stack gap="sm">
          <Text size="sm" c="dimmed">
            识别到 {batch.results.length} 题
            {batch.failed_count > 0
              ? `，${batch.failed_count} 题失败`
              : ""}
          </Text>
          {batch.results.map((extraction) => (
            <ExtractionCard key={extraction.id} extraction={extraction} />
          ))}
        </Stack>
      )}
    </Stack>
  );
}
