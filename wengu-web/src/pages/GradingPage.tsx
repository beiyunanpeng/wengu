import {
  Alert,
  Badge,
  Button,
  Card,
  Divider,
  Group,
  Loader,
  SimpleGrid,
  Stack,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ApiError, errorMessage } from "../api/client";
import { appealGrading, confirmGrading, getGrading } from "../api/endpoints";
import type { GradingDetail } from "../api/types";
import CategoryPicker from "../components/CategoryPicker";
import MathText from "../components/MathText";

const VERDICT_LABELS: Record<string, string> = {
  correct: "答对",
  wrong: "答错",
  uncertain: "待确认",
  pending: "待确认",
};

const STATUS_LABELS: Record<string, string> = {
  pending: "待确认",
  confirmed: "已确认",
  appealed: "已申诉",
};

const ACTION_LABELS: Record<string, string> = {
  suggested: "建议值",
  confirmed: "用户确认",
  appealed: "用户申诉",
};

const SOURCE_LABELS: Record<string, string> = {
  vlm: "视觉模型",
  ai: "模型",
  code: "代码判分",
  student: "学生",
  parent: "家长",
};

const QUESTION_TYPE_LABELS: Record<string, string> = {
  objective: "客观题",
  process: "过程题",
  open: "开放题",
};

export default function GradingPage() {
  const params = useParams();
  const gradingId = params.gradingId ? Number(params.gradingId) : null;
  const navigate = useNavigate();

  const [grading, setGrading] = useState<GradingDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [categoryId, setCategoryId] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);

  async function load(showSpinner = true) {
    if (gradingId === null || Number.isNaN(gradingId)) {
      setLoadError("批改编号无效");
      setLoading(false);
      return;
    }
    if (showSpinner) {
      setLoading(true);
    }
    setLoadError(null);
    try {
      setGrading(await getGrading(gradingId));
    } catch (cause) {
      setLoadError(errorMessage(cause));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gradingId]);

  async function decide(action: "confirm" | "appeal", verdict: "correct" | "wrong") {
    if (!grading || busyAction) {
      return;
    }
    if (verdict === "wrong" && !categoryId) {
      setActionError("确认或申诉为答错前，必须先选择知识点分类");
      return;
    }
    setActionError(null);
    setMessage(null);
    setBusyAction(`${action}-${verdict}`);
    try {
      const payload = {
        base_version: grading.current_version,
        verdict,
        category_id: verdict === "wrong" ? categoryId : null,
      };
      const updated =
        action === "confirm"
          ? await confirmGrading(grading.id, payload)
          : await appealGrading(grading.id, {
              ...payload,
              reason: reason.trim() || "用户申诉",
            });
      setGrading(updated);
      if (verdict === "wrong") {
        setMessage("已写入错题本，并生成首次复习排期。");
      } else if (action === "confirm") {
        setMessage("已确认答对，不会进入错题本。");
      } else {
        setMessage("申诉已记录为答对；如错题已存在，会同步作废。");
      }
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        setActionError("版本已变化，已刷新为最新状态，请重新操作。");
        await load(false);
      } else {
        setActionError(errorMessage(cause));
      }
    } finally {
      setBusyAction(null);
    }
  }

  if (loading) {
    return (
      <Group justify="center" py="xl">
        <Loader />
      </Group>
    );
  }

  if (loadError || !grading) {
    return (
      <Stack gap="md">
        <Title order={2}>批改结果</Title>
        <Alert color="red" variant="light" title="加载失败">
          {loadError ?? "批改不存在"}
        </Alert>
        <Group>
          <Button variant="light" onClick={() => void load()}>
            重试
          </Button>
          <Button variant="subtle" onClick={() => navigate("/capture")}>
            回到采集
          </Button>
        </Group>
      </Stack>
    );
  }

  const latest = grading.versions[grading.versions.length - 1];

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center">
        <Title order={2}>批改结果</Title>
        <Group gap="xs">
          <Badge variant="light">
            {QUESTION_TYPE_LABELS[grading.question_type] ?? grading.question_type}
          </Badge>
          <Badge color={grading.status === "pending" ? "yellow" : "green"}>
            {STATUS_LABELS[grading.status] ?? grading.status}
          </Badge>
        </Group>
      </Group>

      <Card withBorder>
        <Stack gap="sm">
          <Text size="sm" c="dimmed">
            回显核对：题目、孩子作答与参考答案并排展示，确认后再入错题本。
          </Text>
          <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="md">
            <div>
              <Text size="sm" fw={600} mb={4}>
                题目
              </Text>
              <MathText text={grading.problem_text} />
            </div>
            <div>
              <Text size="sm" fw={600} mb={4}>
                孩子作答
              </Text>
              <MathText text={grading.student_answer || "（空）"} />
            </div>
            <div>
              <Text size="sm" fw={600} mb={4}>
                标准答案
              </Text>
              <MathText text={grading.standard_answer || "（未提供）"} />
            </div>
          </SimpleGrid>
        </Stack>
      </Card>

      {latest && (
        <Card withBorder>
          <Stack gap="xs">
            <Group gap="xs">
              <Text fw={600}>当前建议</Text>
              <Badge
                color={
                  latest.verdict === "correct"
                    ? "green"
                    : latest.verdict === "wrong"
                      ? "red"
                      : "yellow"
                }
                variant="light"
              >
                {VERDICT_LABELS[latest.verdict] ?? latest.verdict}
              </Badge>
              {latest.confidence !== null && (
                <Text size="sm" c="dimmed">
                  置信度 {Math.round(latest.confidence * 100)}%
                </Text>
              )}
            </Group>
            {latest.reason && <Text size="sm">原因：{latest.reason}</Text>}
            {latest.sample_verdicts.length > 0 && (
              <Text size="sm" c="dimmed">
                多次采样：{latest.sample_verdicts.join(" / ")}
              </Text>
            )}
            <Text size="xs" c="dimmed">
              来源：{SOURCE_LABELS[latest.source] ?? latest.source}
            </Text>
          </Stack>
        </Card>
      )}

      <Card withBorder>
        <Stack gap="sm">
          <Text fw={600}>确认 / 申诉</Text>
          <CategoryPicker
            value={categoryId}
            onChange={setCategoryId}
            label="知识点分类（答错时必填）"
            placeholder="搜索并选择粗粒度知识点"
          />
          {actionError && (
            <Alert color="red" variant="light">
              {actionError}
            </Alert>
          )}
          {message && (
            <Alert color="green" variant="light">
              {message}
            </Alert>
          )}
          <Group>
            <Button
              color="green"
              variant="light"
              onClick={() => void decide("confirm", "correct")}
              loading={busyAction === "confirm-correct"}
              disabled={Boolean(busyAction)}
            >
              确认答对
            </Button>
            <Button
              color="red"
              onClick={() => void decide("confirm", "wrong")}
              loading={busyAction === "confirm-wrong"}
              disabled={Boolean(busyAction)}
            >
              确认答错并入本
            </Button>
          </Group>
          <Divider label="申诉改判" labelPosition="left" />
          <Textarea
            label="申诉原因（可选）"
            value={reason}
            onChange={(event) => setReason(event.currentTarget.value)}
            autosize
            minRows={1}
            maxRows={3}
            placeholder="例如：标准答案有误 / 作答其实等价"
          />
          <Group>
            <Button
              variant="light"
              onClick={() => void decide("appeal", "correct")}
              loading={busyAction === "appeal-correct"}
              disabled={Boolean(busyAction)}
            >
              申诉为答对
            </Button>
            <Button
              variant="light"
              color="red"
              onClick={() => void decide("appeal", "wrong")}
              loading={busyAction === "appeal-wrong"}
              disabled={Boolean(busyAction)}
            >
              申诉为答错
            </Button>
          </Group>
        </Stack>
      </Card>

      {grading.mistake_id !== null && (
        <Card withBorder>
          <Stack gap="sm">
            <Text fw={600}>下一步</Text>
            <Text size="sm">
              这道题已进入错题本（#{grading.mistake_id}），首次复习排期已生成。
            </Text>
            <Group>
              <Button
                variant="light"
                onClick={() => navigate(`/mistakes/${grading.mistake_id}`)}
              >
                查看错题
              </Button>
              <Button
                variant="light"
                onClick={() =>
                  navigate(
                    `/explain?source_kind=mistake&source_id=${grading.mistake_id}`,
                  )
                }
              >
                看讲解
              </Button>
              <Button variant="subtle" onClick={() => navigate("/review")}>
                去复习
              </Button>
            </Group>
          </Stack>
        </Card>
      )}

      {grading.mistake_id === null && grading.status !== "pending" && (
        <Group>
          <Button variant="light" onClick={() => navigate("/capture")}>
            继续采集
          </Button>
        </Group>
      )}

      <Card withBorder>
        <Stack gap="xs">
          <Text fw={600}>版本历史</Text>
          {grading.versions.map((version) => (
            <Card key={version.version} withBorder padding="sm">
              <Group gap="xs">
                <Badge variant="light">v{version.version}</Badge>
                <Badge variant="outline">
                  {ACTION_LABELS[version.action] ?? version.action}
                </Badge>
                <Text size="sm">
                  {VERDICT_LABELS[version.verdict] ?? version.verdict}
                </Text>
              </Group>
              <Text size="xs" c="dimmed">
                来源：{SOURCE_LABELS[version.source] ?? version.source}
                {version.confidence !== null
                  ? ` · 置信度 ${Math.round(version.confidence * 100)}%`
                  : ""}
              </Text>
              {version.reason && <Text size="sm">{version.reason}</Text>}
            </Card>
          ))}
        </Stack>
      </Card>
    </Stack>
  );
}
