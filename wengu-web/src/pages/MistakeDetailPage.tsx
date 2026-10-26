import {
  Alert,
  Badge,
  Button,
  Card,
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
import { useNavigate, useParams } from "react-router-dom";

import { ApiError, errorMessage } from "../api/client";
import {
  createConcept,
  getMistake,
  getMistakeOptions,
  listConcepts,
  updateMistakeLabels,
} from "../api/endpoints";
import type { Concept, ErrorCauseOption, MistakeDetail } from "../api/types";
import CategoryPicker from "../components/CategoryPicker";
import MathText from "../components/MathText";

export default function MistakeDetailPage() {
  const params = useParams();
  const mistakeId = params.mistakeId ? Number(params.mistakeId) : null;
  const navigate = useNavigate();

  const [detail, setDetail] = useState<MistakeDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [errorCauses, setErrorCauses] = useState<ErrorCauseOption[]>([]);
  const [concepts, setConcepts] = useState<Concept[]>([]);
  const [categoryId, setCategoryId] = useState<string | null>(null);
  const [conceptIds, setConceptIds] = useState<number[]>([]);
  const [errorCause, setErrorCause] = useState<string | null>(null);
  const [newConceptName, setNewConceptName] = useState("");
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  function applyDetail(next: MistakeDetail) {
    setDetail(next);
    const confirmed = next.labels.confirmed;
    const nextCategory = confirmed
      ? next.labels.category_id
      : next.suggestion.category_id;
    const nextConcepts = confirmed
      ? next.labels.concepts
      : next.suggestion.concepts;
    setCategoryId(nextCategory);
    setConceptIds(nextCategory ? nextConcepts.map((concept) => concept.id) : []);
    setErrorCause(
      confirmed ? next.labels.error_cause : next.suggestion.error_cause,
    );
  }

  async function load(showSpinner = true) {
    if (mistakeId === null || Number.isNaN(mistakeId)) {
      setLoadError("错题编号无效");
      setLoading(false);
      return;
    }
    if (showSpinner) {
      setLoading(true);
    }
    setLoadError(null);
    try {
      applyDetail(await getMistake(mistakeId));
    } catch (cause) {
      setLoadError(errorMessage(cause));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mistakeId]);

  useEffect(() => {
    let active = true;
    getMistakeOptions()
      .then((response) => {
        if (active) {
          setErrorCauses(response.error_causes);
        }
      })
      .catch(() => {
        // 错因下拉失败不阻断标签查看；保存时后端仍会校验
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!categoryId) {
      setConcepts([]);
      return;
    }
    let active = true;
    listConcepts({ categoryId })
      .then((response) => {
        if (active) {
          setConcepts(response.items);
        }
      })
      .catch((cause: unknown) => {
        if (active) {
          setActionError(`细标签加载失败：${errorMessage(cause)}`);
        }
      });
    return () => {
      active = false;
    };
  }, [categoryId]);

  async function handleCreateConcept() {
    const name = newConceptName.trim();
    if (!categoryId || !name || creating) {
      return;
    }
    setCreating(true);
    setActionError(null);
    setMessage(null);
    try {
      const created = await createConcept({
        name,
        category_id: categoryId,
      });
      setConcepts((previous) =>
        previous.some((concept) => concept.id === created.id)
          ? previous
          : [...previous, created],
      );
      setConceptIds((previous) =>
        previous.includes(created.id) ? previous : [...previous, created.id],
      );
      setNewConceptName("");
      setMessage(created.reused ? "已复用同名细标签" : "已新建细标签");
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setCreating(false);
    }
  }

  async function saveLabels() {
    if (!detail || saving) {
      return;
    }
    setSaving(true);
    setActionError(null);
    setMessage(null);
    try {
      const updated = await updateMistakeLabels(detail.id, {
        base_version: detail.current_version,
        category_id: categoryId,
        concept_ids: conceptIds,
        error_cause: errorCause,
      });
      applyDetail(updated);
      setMessage("标签已保存");
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        setActionError("版本已变化，已刷新为最新标签，请重新保存");
        await load(false);
      } else {
        setActionError(errorMessage(cause));
      }
    } finally {
      setSaving(false);
    }
  }

  function adoptSuggestion() {
    if (!detail) {
      return;
    }
    setCategoryId(detail.suggestion.category_id);
    setConceptIds(
      detail.suggestion.category_id
        ? detail.suggestion.concepts.map((concept) => concept.id)
        : [],
    );
    setErrorCause(detail.suggestion.error_cause);
  }

  if (loading) {
    return (
      <Group justify="center" py="xl">
        <Loader />
      </Group>
    );
  }

  if (loadError || !detail) {
    return (
      <Stack gap="md">
        <Title order={2}>错题详情</Title>
        <Alert color="red" variant="light" title="加载失败">
          {loadError ?? "错题不存在"}
        </Alert>
        <Group>
          <Button variant="light" onClick={() => void load()}>
            重试
          </Button>
          <Button variant="subtle" onClick={() => navigate("/mistakes")}>
            返回错题本
          </Button>
        </Group>
      </Stack>
    );
  }

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
    <Stack gap="md">
      <Group justify="space-between" align="center">
        <Group gap="xs">
          <Title order={2}>错题 #{detail.id}</Title>
          <Badge color={detail.status === "active" ? "blue" : "gray"}>
            {detail.status === "active" ? "进行中" : "已作废"}
          </Badge>
        </Group>
        <Button variant="subtle" onClick={() => navigate("/mistakes")}>
          返回错题本
        </Button>
      </Group>

      <Card withBorder>
        <Stack gap="sm">
          <div>
            <Text size="sm" fw={600} mb={4}>
              题目
            </Text>
            <MathText text={detail.problem_text || "（无题目文本）"} />
          </div>
          <div>
            <Text size="sm" fw={600} mb={4}>
              孩子作答
            </Text>
            <MathText text={detail.student_answer || "（空）"} />
          </div>
          <div>
            <Text size="sm" fw={600} mb={4}>
              标准答案
            </Text>
            <MathText text={detail.standard_answer || "（未提供）"} />
          </div>
        </Stack>
      </Card>

      <Card withBorder>
        <Stack gap="xs">
          <Group justify="space-between">
            <Text fw={600}>当前标签</Text>
            <Badge color={detail.labels.confirmed ? "green" : "yellow"} variant="light">
              {detail.labels.confirmed ? "已确认" : "未确认"}
            </Badge>
          </Group>
          <Group gap="xs" wrap="wrap">
            <Badge color="blue" variant="light">
              {detail.labels.category_name ??
                detail.suggestion.category_name ??
                "未挂知识点"}
            </Badge>
            {(detail.labels.confirmed
              ? detail.labels.concepts
              : detail.suggestion.concepts
            ).map((concept) => (
              <Badge key={concept.id} variant="outline">
                {concept.name}
              </Badge>
            ))}
            {(detail.labels.error_cause_label ??
              detail.suggestion.error_cause_label) && (
              <Badge color="orange" variant="light">
                {detail.labels.error_cause_label ??
                  detail.suggestion.error_cause_label}
              </Badge>
            )}
          </Group>
          <Text size="xs" c="dimmed">
            建议值只作参考；一旦你保存确认值，后续建议不会覆盖。
          </Text>
          <Group>
            <Button size="compact-sm" variant="light" onClick={adoptSuggestion}>
              采用建议标签
            </Button>
          </Group>
        </Stack>
      </Card>

      <Card withBorder>
        <Stack gap="sm">
          <Text fw={600}>编辑标签</Text>
          <CategoryPicker
            value={categoryId}
            onChange={(value) => {
              setCategoryId(value);
              setConceptIds([]);
              setNewConceptName("");
            }}
            label="粗粒度知识点"
            initialLabel={detail.labels.category_name ?? detail.suggestion.category_name}
          />
          <MultiSelect
            label="细粒度 concept（可多选）"
            data={conceptData}
            value={conceptIds.map(String)}
            onChange={(values) => setConceptIds(values.map(Number))}
            disabled={!categoryId}
            searchable
            clearable
            nothingFoundMessage="这个知识点下还没有细标签"
            placeholder={categoryId ? "选择或搜索细标签" : "先选粗粒度知识点"}
          />
          <Group align="flex-end">
            <TextInput
              label="新建 / 复用细标签"
              value={newConceptName}
              onChange={(event) => setNewConceptName(event.currentTarget.value)}
              placeholder="例如：异号两数相加"
              disabled={!categoryId}
              style={{ flex: 1 }}
            />
            <Button
              variant="light"
              onClick={() => void handleCreateConcept()}
              loading={creating}
              disabled={!categoryId || !newConceptName.trim()}
            >
              新建 / 复用
            </Button>
          </Group>
          <Select
            label="错因"
            data={errorCauses.map((item) => ({
              value: item.id,
              label: item.label,
            }))}
            value={errorCause}
            onChange={setErrorCause}
            clearable
            placeholder="选择错因"
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
            <Button onClick={() => void saveLabels()} loading={saving}>
              保存标签
            </Button>
            <Button
              variant="light"
              onClick={() =>
                navigate(`/explain?source_kind=mistake&source_id=${detail.id}`)
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
    </Stack>
  );
}
