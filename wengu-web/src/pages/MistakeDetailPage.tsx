import {
  Alert,
  Badge,
  Button,
  Card,
  FileButton,
  Group,
  Image,
  Loader,
  Modal,
  MultiSelect,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ApiError, errorMessage } from "../api/client";
import {
  createConcept,
  deleteMistakeImage,
  getMistake,
  getMistakeOptions,
  listConcepts,
  mergeConcepts,
  mistakeImageUrl,
  previewConceptMerge,
  setMistakePrimaryTopic,
  startPractice,
  unvoidMistake,
  updateMistakeLabels,
  updateMistakeNotes,
  uploadMistakeImage,
  voidMistake,
} from "../api/endpoints";
import type {
  Concept,
  ConceptMergePreview,
  ErrorCauseOption,
  MistakeDetail,
  PracticeStartResponse,
} from "../api/types";
import CategoryPicker from "../components/CategoryPicker";
import MathText from "../components/MathText";
import { initialMergeSelection, isMergeSelectionReady } from "./mergeSelection";
import { useParentSession } from "../parent/ParentSession";

export default function MistakeDetailPage() {
  const params = useParams();
  const mistakeId = params.mistakeId ? Number(params.mistakeId) : null;
  const navigate = useNavigate();
  const { unlocked: parentUnlocked } = useParentSession();

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
  const [voidOpen, setVoidOpen] = useState(false);
  const [voidReason, setVoidReason] = useState("");
  const [statusBusy, setStatusBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [practice, setPractice] = useState<PracticeStartResponse | null>(null);
  const [practiceChecking, setPracticeChecking] = useState(true);
  const [practiceError, setPracticeError] = useState<string | null>(null);
  const [mergeOpen, setMergeOpen] = useState(false);
  const [mergeSourceId, setMergeSourceId] = useState<string | null>(null);
  const [mergeTargetId, setMergeTargetId] = useState<string | null>(null);
  const [mergePreview, setMergePreview] = useState<ConceptMergePreview | null>(
    null,
  );
  const [mergePreviewLoading, setMergePreviewLoading] = useState(false);
  const [mergeError, setMergeError] = useState<string | null>(null);
  const [mergeBusy, setMergeBusy] = useState(false);
  const [imageBusy, setImageBusy] = useState(false);
  const [imageError, setImageError] = useState<string | null>(null);
  const [removeIndex, setRemoveIndex] = useState<number | null>(null);
  const [notesEditing, setNotesEditing] = useState(false);
  const [notesDraft, setNotesDraft] = useState("");
  const [notesSaving, setNotesSaving] = useState(false);
  const [notesError, setNotesError] = useState<string | null>(null);
  const [primaryTopicDraft, setPrimaryTopicDraft] = useState<string | null>(null);
  const [primarySaving, setPrimarySaving] = useState(false);
  const [primaryError, setPrimaryError] = useState<string | null>(null);
  const [primaryMessage, setPrimaryMessage] = useState<string | null>(null);

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
    setNotesEditing(false);
    setNotesDraft(next.correction_notes ?? "");
    setNotesError(null);
    setPrimaryTopicDraft(next.primary_topic_id);
    setPrimaryError(null);
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

  useEffect(() => {
    if (mistakeId === null || Number.isNaN(mistakeId)) {
      setPracticeChecking(false);
      return;
    }
    let active = true;
    setPracticeChecking(true);
    startPractice({ mistakeId, count: 1 })
      .then((response) => {
        if (active) {
          setPractice(response);
          setPracticeError(null);
        }
      })
      .catch((cause: unknown) => {
        if (active) {
          setPractice(null);
          setPracticeError(errorMessage(cause));
        }
      })
      .finally(() => {
        if (active) {
          setPracticeChecking(false);
        }
      });
    return () => {
      active = false;
    };
  }, [mistakeId]);

  useEffect(() => {
    if (
      !mergeOpen ||
      !isMergeSelectionReady({
        sourceId: mergeSourceId,
        targetId: mergeTargetId,
      })
    ) {
      setMergePreview(null);
      setMergePreviewLoading(false);
      return;
    }
    let active = true;
    setMergePreviewLoading(true);
    setMergeError(null);
    previewConceptMerge({
      source_id: Number(mergeSourceId),
      target_id: Number(mergeTargetId),
    })
      .then((response) => {
        if (active) {
          setMergePreview(response);
        }
      })
      .catch((cause: unknown) => {
        if (active) {
          setMergePreview(null);
          setMergeError(errorMessage(cause));
        }
      })
      .finally(() => {
        if (active) {
          setMergePreviewLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [mergeOpen, mergeSourceId, mergeTargetId]);

  function openMerge() {
    const initial = initialMergeSelection(conceptIds);
    setMergeSourceId(initial.sourceId);
    setMergeTargetId(initial.targetId);
    setMergePreview(null);
    setMergeError(null);
    setMergeOpen(true);
  }

  async function handleMerge() {
    if (
      mergeBusy ||
      !isMergeSelectionReady({
        sourceId: mergeSourceId,
        targetId: mergeTargetId,
      })
    ) {
      return;
    }
    setMergeBusy(true);
    setMergeError(null);
    try {
      await mergeConcepts({
        source_id: Number(mergeSourceId),
        target_id: Number(mergeTargetId),
        actor: "parent",
      });
    } catch (cause) {
      setMergeError(errorMessage(cause));
      setMergeBusy(false);
      return;
    }
    setMergeOpen(false);
    setMergeSourceId(null);
    setMergeTargetId(null);
    setMergePreview(null);
    setMergeBusy(false);
    setMessage("历史错题标签与事件未改动，仅名称解析指向最终概念");
    try {
      if (categoryId) {
        const response = await listConcepts({ categoryId });
        setConcepts(response.items);
      }
      await load(false);
    } catch (cause) {
      setActionError(`归并成功，但刷新失败：${errorMessage(cause)}`);
    }
  }

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

  async function saveNotes() {
    if (!detail || notesSaving) {
      return;
    }
    setNotesSaving(true);
    setNotesError(null);
    try {
      const updated = await updateMistakeNotes(detail.id, {
        base_version: detail.current_version,
        correction_notes: notesDraft.trim(),
      });
      applyDetail(updated);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        setNotesError("版本已变化，已刷新为最新内容，请重新编辑");
        await load(false);
      } else {
        setNotesError(errorMessage(cause));
      }
    } finally {
      setNotesSaving(false);
    }
  }

  async function savePrimaryTopic(nextValue: string | null) {
    if (!detail || primarySaving) {
      return;
    }
    setPrimarySaving(true);
    setPrimaryError(null);
    setPrimaryMessage(null);
    try {
      const updated = await setMistakePrimaryTopic(detail.id, {
        base_version: detail.current_version,
        primary_topic_id: nextValue,
      });
      applyDetail(updated);
      setPrimaryMessage(nextValue === null ? "主考点已清除" : "主考点已保存");
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        setPrimaryError("版本已变化，已刷新为最新内容，请重新保存");
        await load(false);
      } else {
        setPrimaryError(errorMessage(cause));
      }
    } finally {
      setPrimarySaving(false);
    }
  }

  async function handleVoid() {
    if (!detail || statusBusy) {
      return;
    }
    setStatusBusy(true);
    setActionError(null);
    setMessage(null);
    try {
      const updated = await voidMistake(detail.id, {
        reason: voidReason.trim() || null,
      });
      applyDetail(updated);
      setVoidOpen(false);
      setVoidReason("");
      setMessage("已作废：退出活跃列表与到期队列，历史版本与复习记录保留");
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setStatusBusy(false);
    }
  }

  async function handleUnvoid() {
    if (!detail || statusBusy) {
      return;
    }
    setStatusBusy(true);
    setActionError(null);
    setMessage(null);
    try {
      applyDetail(await unvoidMistake(detail.id));
      setMessage("已撤销作废；未完成排期到期后会重新进入复习队列");
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setStatusBusy(false);
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

  async function handleUploadImage(file: File | null) {
    if (!file || !detail || imageBusy) {
      return;
    }
    setImageBusy(true);
    setImageError(null);
    try {
      // 只刷新详情，不重置尚未保存的标签编辑。
      setDetail(await uploadMistakeImage(detail.id, file));
    } catch (cause) {
      setImageError(errorMessage(cause));
    } finally {
      setImageBusy(false);
    }
  }

  async function handleRemoveImage() {
    if (!detail || removeIndex === null || imageBusy) {
      return;
    }
    setImageBusy(true);
    setImageError(null);
    try {
      setDetail(await deleteMistakeImage(detail.id, removeIndex));
      setRemoveIndex(null);
    } catch (cause) {
      setImageError(errorMessage(cause));
    } finally {
      setImageBusy(false);
    }
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
  const mergeData = concepts
    .filter((concept) => concept.category_id === categoryId)
    .map((concept) => ({ value: String(concept.id), label: concept.name }));

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center">
        <Group gap="xs">
          <Title order={2}>错题 #{detail.id}</Title>
          <Badge color={detail.status === "active" ? "blue" : "gray"}>
            {detail.status === "active" ? "进行中" : "已作废"}
          </Badge>
        </Group>
        <Group gap="xs">
          {parentUnlocked ? (
            detail.status === "active" ? (
              <Button
                color="red"
                variant="light"
                onClick={() => setVoidOpen(true)}
              >
                作废错题
              </Button>
            ) : (
              <Button
                variant="light"
                onClick={() => void handleUnvoid()}
                loading={statusBusy}
              >
                撤销作废
              </Button>
            )
          ) : (
            <Text size="xs" c="dimmed">
              作废/撤销需先在右上角「家长区」输入 PIN
            </Text>
          )}
          <Button variant="subtle" onClick={() => navigate("/mistakes")}>
            返回错题本
          </Button>
        </Group>
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
          <div>
            <Group justify="space-between" align="center" mb={4}>
              <Text size="sm" fw={600}>
                订正笔记
              </Text>
              {detail.status === "active" && !notesEditing && (
                <Button
                  size="compact-xs"
                  variant="light"
                  onClick={() => {
                    setNotesDraft(detail.correction_notes ?? "");
                    setNotesError(null);
                    setNotesEditing(true);
                  }}
                >
                  编辑笔记
                </Button>
              )}
            </Group>
            {notesEditing ? (
              <Stack gap="xs">
                <Textarea
                  value={notesDraft}
                  onChange={(event) => setNotesDraft(event.currentTarget.value)}
                  placeholder="只抄卷面上孩子/家长手写的订正批注；留空表示无笔记"
                  maxLength={500}
                  autosize
                  minRows={2}
                />
                <Text size="xs" c="dimmed">
                  只转录卷面手写笔记，系统不生成讲解；笔记不影响判分、复习与掌握度。
                </Text>
                {notesError && (
                  <Alert color="red" variant="light">
                    {notesError}
                  </Alert>
                )}
                <Group gap="xs">
                  <Button
                    size="compact-sm"
                    onClick={() => void saveNotes()}
                    loading={notesSaving}
                  >
                    保存笔记
                  </Button>
                  <Button
                    size="compact-sm"
                    variant="subtle"
                    disabled={notesSaving}
                    onClick={() => {
                      setNotesEditing(false);
                      setNotesError(null);
                    }}
                  >
                    取消
                  </Button>
                </Group>
              </Stack>
            ) : (
              <MathText text={detail.correction_notes || "（无手写笔记）"} />
            )}
          </div>
          <div>
            <Text size="sm" fw={600} mb={4}>
              原题图（{detail.problem_images.length}/3）
            </Text>
            {detail.problem_images.length > 0 && (
              <Group gap="sm" wrap="wrap" mb={8}>
                {detail.problem_images.map((path, index) => (
                  <Stack key={path} gap={4} align="center">
                    <Image
                      src={mistakeImageUrl(detail.id, index)}
                      alt={`原题图 ${index + 1}`}
                      w={140}
                      h={140}
                      fit="cover"
                      radius="sm"
                    />
                    <Button
                      size="compact-xs"
                      color="red"
                      variant="light"
                      disabled={imageBusy}
                      onClick={() => {
                        setImageError(null);
                        setRemoveIndex(index);
                      }}
                    >
                      移除
                    </Button>
                  </Stack>
                ))}
              </Group>
            )}
            <Group gap="xs" align="center">
              <FileButton
                onChange={(file) => void handleUploadImage(file)}
                accept="image/png,image/jpeg,image/webp"
                disabled={imageBusy || detail.problem_images.length >= 3}
              >
                {(props) => (
                  <Button
                    {...props}
                    variant="light"
                    size="compact-sm"
                    loading={imageBusy}
                    disabled={imageBusy || detail.problem_images.length >= 3}
                  >
                    上传原题图
                  </Button>
                )}
              </FileButton>
              {detail.problem_images.length >= 3 && (
                <Text size="xs" c="dimmed">
                  已达 3 张上限，移除后才能再传
                </Text>
              )}
            </Group>
            {imageError && removeIndex === null && (
              <Alert color="red" variant="light" mt={8}>
                {imageError}
              </Alert>
            )}
            <Text size="xs" c="dimmed" mt={4}>
              仅支持 JPEG/PNG/WebP，单张 ≤5MB；图片只作附件保存，不做识别。
            </Text>
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
          <Group justify="space-between" align="center">
            <Text fw={600}>主考点</Text>
            <Badge
              color={detail.primary_topic_id ? "blue" : "gray"}
              variant="light"
            >
              {detail.primary_topic_subject}
            </Badge>
          </Group>
          <Text size="xs" c="dimmed">
            主考点决定到期时按哪个知识点检索同类题考核：有题就考、系统判分；
            未挂考点只排原题重做自评。它不影响掌握度、复习间隔与打卡。
          </Text>
          {detail.status !== "active" && (
            <Alert color="gray" variant="light">
              错题已作废：主考点只读。撤销作废后可继续修改。
            </Alert>
          )}
          <CategoryPicker
            value={primaryTopicDraft}
            onChange={setPrimaryTopicDraft}
            label="设定 / 更正主考点"
            disabled={detail.status !== "active"}
          />
          {primaryError && (
            <Alert color="red" variant="light">
              {primaryError}
            </Alert>
          )}
          {primaryMessage && (
            <Alert color="green" variant="light">
              {primaryMessage}
            </Alert>
          )}
          <Group>
            <Button
              onClick={() => void savePrimaryTopic(primaryTopicDraft)}
              loading={primarySaving}
              disabled={detail.status !== "active"}
            >
              保存主考点
            </Button>
            <Button
              variant="subtle"
              onClick={() => {
                setPrimaryTopicDraft(null);
                void savePrimaryTopic(null);
              }}
              loading={primarySaving}
              disabled={
                detail.status !== "active" || primaryTopicDraft === null
              }
            >
              清除
            </Button>
          </Group>
        </Stack>
      </Card>

      <Card withBorder>
        <Stack gap="sm">
          <Text fw={600}>编辑标签</Text>
          {detail.status !== "active" && (
            <Alert color="gray" variant="light">
              错题已作废：标签只读。撤销作废后可继续修改。
            </Alert>
          )}
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
          {parentUnlocked && (
            <Group align="center" gap="xs" wrap="wrap">
              <Button
                variant="light"
                onClick={openMerge}
                disabled={!categoryId || mergeData.length < 2}
              >
                归并知识点
              </Button>
              <Text size="xs" c="dimmed">
                把重复建出的细标签并入同一粗粒度知识点；仅家长可见。
              </Text>
            </Group>
          )}
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
            <Button
              onClick={() => void saveLabels()}
              loading={saving}
              disabled={detail.status !== "active"}
            >
              保存标签
            </Button>
            <Button variant="subtle" onClick={() => navigate("/review")}>
              去复习
            </Button>
          </Group>
          <Group align="center">
            <Button
              variant="light"
              onClick={() => navigate(`/practice?mistake_id=${detail.id}`)}
              loading={practiceChecking}
              disabled={
                practiceChecking ||
                practice === null ||
                practice.items.length === 0
              }
            >
              加练同类题
            </Button>
            {practiceChecking && (
              <Text size="xs" c="dimmed">
                正在检查同类题…
              </Text>
            )}
            {!practiceChecking &&
              practice &&
              practice.items.length === 0 && (
                <Text size="xs" c="dimmed">
                  {practice.message ?? "该知识点暂无同类题"}
                </Text>
              )}
            {!practiceChecking && practiceError && (
              <Text size="xs" c="red">
                同类题检查失败：{practiceError}
              </Text>
            )}
          </Group>
          <Text size="xs" c="dimmed">
            加练只写练习记录：不进错题本、不影响掌握度与复习排期。
          </Text>
          <Text size="xs" c="dimmed">
            v2.5：批改与讲解在系统外完成（卷面红笔 + 拿不准找豆包/家长）；
            系统只记录与复习，不生成讲解。
          </Text>
        </Stack>
      </Card>

      <Modal
        opened={removeIndex !== null}
        onClose={() => {
          setRemoveIndex(null);
          setImageError(null);
        }}
        title="移除原题图"
      >
        <Stack gap="sm">
          <Text size="sm">
            移除后该图片从附件列表删除并删掉磁盘文件，不可恢复；不影响错题文本、标签与复习记录。
          </Text>
          {imageError && (
            <Alert color="red" variant="light">
              {imageError}
            </Alert>
          )}
          <Group justify="flex-end">
            <Button
              variant="subtle"
              onClick={() => {
                setRemoveIndex(null);
                setImageError(null);
              }}
            >
              取消
            </Button>
            <Button
              color="red"
              onClick={() => void handleRemoveImage()}
              loading={imageBusy}
            >
              确认移除
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={voidOpen}
        onClose={() => setVoidOpen(false)}
        title="作废错题"
      >
        <Stack gap="sm">
          <Text size="sm">
            作废后该错题退出错题本活跃列表与到期复习队列；历史版本、复习记录与事件全部保留，可随时撤销。
          </Text>
          <TextInput
            label="作废原因（可选）"
            value={voidReason}
            maxLength={200}
            onChange={(event) => setVoidReason(event.currentTarget.value)}
            placeholder="例如：已当面讲通，不需要再复习"
          />
          <Group justify="flex-end">
            <Button variant="subtle" onClick={() => setVoidOpen(false)}>
              取消
            </Button>
            <Button
              color="red"
              onClick={() => void handleVoid()}
              loading={statusBusy}
            >
              确认作废
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={mergeOpen}
        onClose={() => setMergeOpen(false)}
        title="归并知识点"
      >
        <Stack gap="sm">
          <Alert color="red" variant="light" title="归并方向与后果">
            方向别弄反：源概念会被并入、之后从列表消失；目标是最终保留的概念。
            源名称/别名并入目标；历史错题的标签与事件不会被改写，读取时按名称解析指向最终概念。
          </Alert>
          <Select
            label="源概念（将被并入，之后从列表消失）"
            data={mergeData}
            value={mergeSourceId}
            onChange={setMergeSourceId}
            searchable
            placeholder="选择要被并入的细标签"
          />
          <Select
            label="目标概念（最终保留）"
            data={mergeData}
            value={mergeTargetId}
            onChange={setMergeTargetId}
            searchable
            placeholder="选择最终保留的细标签"
          />
          {mergeSourceId && mergeSourceId === mergeTargetId && (
            <Alert color="orange" variant="light">
              源与目标必须是两个不同的概念。
            </Alert>
          )}
          {mergePreviewLoading && (
            <Text size="xs" c="dimmed">
              正在读取影响范围…
            </Text>
          )}
          {mergePreview && (
            <Text size="sm">
              {mergePreview.source.name} → {mergePreview.target.name} · 将并入{" "}
              {mergePreview.projected_aliases_moved} 个别名 · 影响{" "}
              {mergePreview.affected_mistakes} 道错题
            </Text>
          )}
          {mergePreview && !mergePreview.same_category && (
            <Alert color="orange" variant="light">
              只能在同一知识点下归并。
            </Alert>
          )}
          {mergeError && (
            <Alert color="red" variant="light" title="归并失败">
              {mergeError}
            </Alert>
          )}
          <Group justify="flex-end">
            <Button
              variant="default"
              onClick={() => setMergeOpen(false)}
              disabled={mergeBusy}
            >
              取消
            </Button>
            <Button
              onClick={() => void handleMerge()}
              loading={mergeBusy}
              disabled={
                !isMergeSelectionReady({
                  sourceId: mergeSourceId,
                  targetId: mergeTargetId,
                }) ||
                !mergePreview ||
                !mergePreview.same_category
              }
            >
              确认归并
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
