import {
  Alert,
  Badge,
  Button,
  Card,
  Grid,
  Group,
  Loader,
  MultiSelect,
  Select,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { errorMessage } from "../api/client";
import {
  confirmIntakeDraft,
  createConcept,
  getMistakeOptions,
  listConcepts,
  listIntakeDrafts,
} from "../api/endpoints";
import type {
  Concept,
  DraftConfirmResponse,
  ErrorCauseOption,
  IntakeDraft,
} from "../api/types";
import CategoryPicker from "../components/CategoryPicker";
import MathText from "../components/MathText";

const PLACEHOLDER = "〔?〕";
const PAGE_SIZE = 50;

function Field({ label, value }: { label: string; value: string }) {
  return (
    <Card withBorder padding="sm" h="100%">
      <Text size="xs" c="dimmed" fw={600} mb={6}>
        {label}
      </Text>
      <MathText text={value || "（空）"} />
    </Card>
  );
}

function DraftCard({
  draft,
  errorCauses,
}: {
  draft: IntakeDraft;
  errorCauses: ErrorCauseOption[];
}) {
  const navigate = useNavigate();
  const [topicId, setTopicId] = useState<string | null>(
    draft.suggestion.topic_id,
  );
  const [conceptIds, setConceptIds] = useState<number[]>([]);
  const [errorCause, setErrorCause] = useState<string | null>(
    draft.suggestion.error_cause,
  );
  const [standardAnswer, setStandardAnswer] = useState(
    draft.standard_answer === PLACEHOLDER ? "" : draft.standard_answer,
  );
  const [actor, setActor] = useState<"student" | "parent">("parent");
  const [concepts, setConcepts] = useState<Concept[]>([]);
  const [newConceptName, setNewConceptName] = useState("");
  const [creating, setCreating] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [result, setResult] = useState<DraftConfirmResponse | null>(null);

  useEffect(() => {
    if (!topicId) {
      setConcepts([]);
      return;
    }
    let active = true;
    listConcepts({ categoryId: topicId })
      .then((response) => {
        if (active) {
          setConcepts(response.items);
        }
      })
      .catch(() => {
        // 细标签列表失败不阻断确认；后端仍会校验所选 id
      });
    return () => {
      active = false;
    };
  }, [topicId]);

  async function handleCreateConcept() {
    const name = newConceptName.trim();
    if (!topicId || !name || creating) {
      return;
    }
    setCreating(true);
    setActionError(null);
    try {
      const created = await createConcept({ name, category_id: topicId });
      setConcepts((previous) =>
        previous.some((concept) => concept.id === created.id)
          ? previous
          : [...previous, created],
      );
      setConceptIds((previous) =>
        previous.includes(created.id) ? previous : [...previous, created.id],
      );
      setNewConceptName("");
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setCreating(false);
    }
  }

  async function handleConfirm() {
    if (blockingReason || submitting) {
      return;
    }
    setSubmitting(true);
    setActionError(null);
    try {
      const response = await confirmIntakeDraft(draft.id, {
        primary_topic_id: topicId,
        standard_answer: standardAnswer.trim(),
        error_cause: errorCause,
        concept_ids: conceptIds,
        actor,
      });      setResult(response);
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setSubmitting(false);
    }
  }

  const placeholderInProblem = draft.problem_text.includes(PLACEHOLDER);
  const placeholderInStudent = draft.student_answer.includes(PLACEHOLDER);
  const blockingReason = placeholderInProblem
    ? "题目含占位符〔?〕，请重新拍照转录"
    : placeholderInStudent
      ? "错答含占位符〔?〕，请重新拍照转录"
      : !standardAnswer.trim()
        ? "缺正答：请补填卷面订正后的答案"
        : standardAnswer.includes(PLACEHOLDER)
          ? "正答仍含占位符，请补全"
          : null;

  const conceptData = concepts.map((concept) => ({
    value: String(concept.id),
    label: concept.name,
  }));
  for (const id of conceptIds) {
    if (!conceptData.some((option) => option.value === String(id))) {
      conceptData.push({ value: String(id), label: `#${id}` });
    }
  }

  return (
    <Card withBorder>
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start" wrap="wrap">
          <Group gap="xs" wrap="wrap">
            <Badge variant="light">草稿 #{draft.id}</Badge>
            {draft.subject && <Badge variant="outline">{draft.subject}</Badge>}
            {draft.has_placeholder && (
              <Badge color="red" variant="light">
                含占位符
              </Badge>
            )}
            {draft.is_incomplete && (
              <Badge color="orange" variant="light">
                字段残缺
              </Badge>
            )}
          </Group>
          <Text size="xs" c="dimmed">
            {draft.source_ref || draft.filename || "出处未知"}
            {draft.captured_at ? ` · ${draft.captured_at}` : ""}
          </Text>
        </Group>

        <Grid gutter="sm">
          <Grid.Col span={{ base: 12, md: 4 }}>
            <Field label="题目（卷面原文）" value={draft.problem_text} />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 4 }}>
            <Field label="错答（被红笔判错）" value={draft.student_answer} />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 4 }}>
            <Field label="正答（卷面订正）" value={standardAnswer} />
          </Grid.Col>
        </Grid>

        <Group gap="xs" wrap="wrap">
          <Text size="xs" c="dimmed">
            建议来源：
            {draft.suggestion.source === "agent"
              ? "AI 转录建议（需你确认）"
              : draft.suggestion.source === "deterministic"
                ? "确定性名称匹配（需你确认）"
                : "无建议，请手动选择"}
          </Text>
          {draft.suggestion.error_cause_label && (
            <Badge color="orange" variant="light">
              建议错因：{draft.suggestion.error_cause_label}
            </Badge>
          )}
        </Group>

        <TextInput
          label="正答（可修改）"
          value={standardAnswer}
          onChange={(event) => setStandardAnswer(event.currentTarget.value)}
          placeholder="卷面没有订正答案时，请在这里补填"
          maxLength={500}
        />

        <CategoryPicker
          value={topicId}
          onChange={(value) => {
            setTopicId(value);
            setConceptIds([]);
            setNewConceptName("");
          }}
          label="主考点（primary_topic_id，可空）"
          initialLabel={draft.suggestion.topic_name}
        />

        <MultiSelect
          label="细粒度概念（可多选）"
          data={conceptData}
          value={conceptIds.map(String)}
          onChange={(values) => setConceptIds(values.map(Number))}
          disabled={!topicId}
          searchable
          clearable
          nothingFoundMessage="这个知识点下还没有细标签"
          placeholder={topicId ? "选择或搜索细标签" : "先选主考点"}
        />

        <Group align="flex-end">
          <TextInput
            label="新建 / 复用细标签"
            value={newConceptName}
            onChange={(event) => setNewConceptName(event.currentTarget.value)}
            placeholder="例如：移项变号"
            disabled={!topicId}
            style={{ flex: 1 }}
          />
          <Button
            variant="light"
            onClick={() => void handleCreateConcept()}
            loading={creating}
            disabled={!topicId || !newConceptName.trim()}
          >
            新建 / 复用
          </Button>
        </Group>

        <Group align="flex-end" wrap="wrap">
          <Select
            label="错因（确认值）"
            data={errorCauses.map((item) => ({
              value: item.id,
              label: item.label,
            }))}
            value={errorCause}
            onChange={setErrorCause}
            clearable
            placeholder="选择错因"
            w={200}
          />
          <Select
            label="确认人"
            data={[
              { value: "parent", label: "家长" },
              { value: "student", label: "孩子" },
            ]}
            value={actor}
            onChange={(value) =>
              setActor(value === "student" ? "student" : "parent")
            }
            w={120}
          />
          <Button
            onClick={() => void handleConfirm()}
            loading={submitting}
            disabled={Boolean(blockingReason) || result !== null}
          >
            确认入本
          </Button>
          {blockingReason && !result && (
            <Text size="sm" c="orange">
              {blockingReason}
            </Text>
          )}
        </Group>

        {actionError && (
          <Alert color="red" variant="light">
            {actionError}
          </Alert>
        )}

        {result && (
          <Alert
            color={result.already_promoted ? "blue" : "green"}
            variant="light"
            title={result.already_promoted ? "这条已在错题本" : "已入本"}
          >
            <Stack gap={4}>
              <Text size="sm">
                错题 #{result.mistake_id} · 主考点{" "}
                {result.primary_topic_id ?? "未指定"} · 正答{" "}
                {result.standard_answer}
              </Text>
              <Text size="xs" c="dimmed">
                {result.due_on
                  ? `首次复习到期：${result.due_on}${
                      result.primary_topic_id
                        ? ""
                        : "（未确认主考点：只做原题重做自评，不推同类题考核）"
                    }`
                  : "尚未生成复习排期"}
              </Text>
              <Group gap="xs">
                <Button
                  size="compact-sm"
                  variant="light"
                  onClick={() => navigate(`/mistakes/${result.mistake_id}`)}
                >
                  查看错题并补标签
                </Button>
                <Button
                  size="compact-sm"
                  variant="subtle"
                  onClick={() => navigate("/review")}
                >
                  去复习
                </Button>
              </Group>
            </Stack>
          </Alert>
        )}
      </Stack>
    </Card>
  );
}

export default function IntakePage() {
  const [drafts, setDrafts] = useState<IntakeDraft[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [errorCauses, setErrorCauses] = useState<ErrorCauseOption[]>([]);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let active = true;
    getMistakeOptions()
      .then((response) => {
        if (active) {
          setErrorCauses(response.error_causes);
        }
      })
      .catch(() => {
        // 错因下拉失败不阻断核对页主流程；后端仍会校验
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    listIntakeDrafts({ status: "draft", limit: PAGE_SIZE })
      .then((response) => {
        if (!active) {
          return;
        }
        setDrafts(response.items);
        setTotal(response.total);
        setError(null);
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
  }, [refreshKey]);

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center">
        <Title order={2}>入库核对</Title>
        <Group gap="xs">
          <Text size="sm" c="dimmed">
            待确认 {total} 条
          </Text>
          <Button
            size="compact-sm"
            variant="subtle"
            onClick={() => setRefreshKey((value) => value + 1)}
          >
            刷新
          </Button>
        </Group>
      </Group>

      <Alert color="blue" variant="light">
        外部 agent 转录的错题只会停在这里；确认后才进错题本、才排复习。题目/错答
        含占位符的草稿需要重新拍照转录。
      </Alert>

      {loading && (
        <Group justify="center" py="xl">
          <Loader />
        </Group>
      )}
      {error && (
        <Alert color="red" variant="light" title="加载失败">
          {error}
        </Alert>
      )}

      {!loading && !error && drafts.length === 0 && (
        <Alert color="gray" variant="light" title="没有待确认草稿">
          把外部 agent 转录好的 JSON 放进 inbox 监听目录（或走 /api/imports），
          刷新后就会出现在这里。
        </Alert>
      )}

      {drafts.map((draft) => (
        <DraftCard key={draft.id} draft={draft} errorCauses={errorCauses} />
      ))}
    </Stack>
  );
}
