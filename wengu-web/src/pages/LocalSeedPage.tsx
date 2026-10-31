import {
  Alert,
  Badge,
  Button,
  Card,
  Grid,
  Group,
  Loader,
  Modal,
  NumberInput,
  SegmentedControl,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { useEffect, useState } from "react";

import { errorMessage } from "../api/client";
import {
  createLocalTopic,
  deleteLocalTopic,
  listLocalTopics,
  updateLocalTopic,
} from "../api/endpoints";
import type {
  LocalTopicCreatePayload,
  LocalTopicInfo,
  LocalTopicList,
  LocalTopicUpdatePayload,
} from "../api/types";
import { useParentSession } from "../parent/ParentSession";

const SUBJECTS = ["语文", "化学"] as const;
type Subject = (typeof SUBJECTS)[number];

interface FormValues {
  name: string;
  grade: string;
  semester: string;
  chapter: string;
  domain: string;
  type: string;
  description: string;
  criteria: string;
}

const EMPTY_FORM: FormValues = {
  name: "",
  grade: "",
  semester: "",
  chapter: "",
  domain: "",
  type: "",
  description: "",
  criteria: "",
};

function toForm(item: LocalTopicInfo): FormValues {
  return {
    name: item.name,
    grade: item.grade ?? "",
    semester: item.semester ?? "",
    chapter: item.chapter ?? "",
    domain: item.domain ?? "",
    type: item.type ?? "",
    description: item.description ?? "",
    criteria: (item.mastery_criteria ?? []).join("\n"),
  };
}

function splitLines(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function payloadOf(form: FormValues): LocalTopicUpdatePayload {
  const grade = form.grade.trim();
  return {
    name: form.name.trim(),
    grade: grade ? Number(grade) : null,
    semester: form.semester.trim() || null,
    chapter: form.chapter.trim() || null,
    domain: form.domain.trim() || null,
    type: form.type.trim() || null,
    description: form.description.trim() || null,
    mastery_criteria: splitLines(form.criteria),
  };
}

function TopicFormModal({
  subject,
  item,
  onClose,
  onSaved,
}: {
  subject: Subject;
  item: LocalTopicInfo | null;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const [form, setForm] = useState<FormValues>(item ? toForm(item) : EMPTY_FORM);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function set<K extends keyof FormValues>(key: K, value: FormValues[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function save() {
    if (busy) {
      return;
    }
    if (!form.name.trim()) {
      setError("名称不能为空");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const payload = payloadOf(form);
      if (item) {
        const response = await updateLocalTopic(item.id, payload);
        onSaved(`${response.id} 已更新（文件真源已同步重写）`);
      } else {
        const createPayload: LocalTopicCreatePayload = { ...payload, subject };
        const response = await createLocalTopic(createPayload);
        onSaved(`${response.id} 已创建（已写入 seeds_local 并装载入库）`);
      }
      onClose();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      opened
      onClose={onClose}
      title={item ? `编辑知识点 ${item.id}` : `新增${subject}知识点`}
      size="lg"
    >
      <Stack gap="sm">
        <Alert color="blue" variant="light">
          章级知识点即可（全科 40–80 点）；细粒度仍走错题受控生长。
          保存会原子重写 `seeds_local/topics_{subject}.json` 并同步 knowledge_seed。
        </Alert>

        <TextInput
          label="名称"
          required
          value={form.name}
          onChange={(event) => set("name", event.currentTarget.value)}
          maxLength={40}
          autoFocus
        />

        <Grid gutter="sm">
          <Grid.Col span={{ base: 6, md: 3 }}>
            <NumberInput
              label="年级"
              value={form.grade === "" ? "" : Number(form.grade)}
              onChange={(value) => set("grade", value === "" ? "" : String(value))}
              min={7}
              max={9}
              allowDecimal={false}
              placeholder="7–9"
            />
          </Grid.Col>
          <Grid.Col span={{ base: 6, md: 3 }}>
            <TextInput
              label="学期"
              value={form.semester}
              onChange={(event) => set("semester", event.currentTarget.value)}
              maxLength={20}
              placeholder="上册"
            />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 3 }}>
            <TextInput
              label="章"
              value={form.chapter}
              onChange={(event) => set("chapter", event.currentTarget.value)}
              maxLength={100}
              placeholder="第一单元 春"
            />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 3 }}>
            <TextInput
              label="领域（可选）"
              value={form.domain}
              onChange={(event) => set("domain", event.currentTarget.value)}
              maxLength={40}
            />
          </Grid.Col>
        </Grid>

        <TextInput
          label="类型（可选）"
          value={form.type}
          onChange={(event) => set("type", event.currentTarget.value)}
          maxLength={20}
          placeholder="conceptual / procedural / …"
        />

        <Textarea
          label="描述（可选）"
          value={form.description}
          onChange={(event) => set("description", event.currentTarget.value)}
          maxLength={500}
          minRows={2}
        />

        <Textarea
          label="掌握标准（可选，每行一条）"
          value={form.criteria}
          onChange={(event) => set("criteria", event.currentTarget.value)}
          minRows={2}
        />

        {error && (
          <Alert color="red" variant="light" title="保存失败">
            {error}
          </Alert>
        )}

        <Group justify="flex-end">
          <Button variant="default" onClick={onClose} disabled={busy}>
            取消
          </Button>
          <Button onClick={() => void save()} loading={busy}>
            {item ? "保存修改" : "创建知识点"}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function TopicCard({
  item,
  onEdit,
  onDelete,
}: {
  item: LocalTopicInfo;
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <Card withBorder>
      <Stack gap="xs">
        <Group justify="space-between" align="flex-start" wrap="wrap">
          <Group gap="xs" wrap="wrap">
            <Badge variant="light">{item.id}</Badge>
            <Text fw={600}>{item.name}</Text>
            {item.grade && (
              <Badge variant="outline" color="gray">
                {item.grade} 年级
              </Badge>
            )}
            {item.semester && (
              <Badge variant="outline" color="gray">
                {item.semester}
              </Badge>
            )}
            {item.chapter && (
              <Badge variant="outline" color="blue">
                {item.chapter}
              </Badge>
            )}
            {item.type && (
              <Badge variant="outline" color="grape">
                {item.type}
              </Badge>
            )}
            <Badge color="orange" variant="light">
              家长自建 · 未经教师审核
            </Badge>
          </Group>
          <Group gap="xs">
            <Button size="compact-sm" variant="light" onClick={onEdit}>
              编辑
            </Button>
            <Button size="compact-sm" variant="light" color="red" onClick={onDelete}>
              删除
            </Button>
          </Group>
        </Group>

        {item.domain && (
          <Text size="xs" c="dimmed">
            领域：{item.domain}
          </Text>
        )}
        {item.description && <Text size="sm">{item.description}</Text>}
        {item.mastery_criteria && item.mastery_criteria.length > 0 && (
          <Text size="xs" c="dimmed">
            掌握标准：{item.mastery_criteria.join("；")}
          </Text>
        )}
        <Text size="xs" c="dimmed">
          引用：错题 {item.mistake_count} 道 · 题库 {item.problem_count} 道
        </Text>
      </Stack>
    </Card>
  );
}

export default function LocalSeedPage() {
  const { unlocked, loading: sessionLoading } = useParentSession();
  const [subject, setSubject] = useState<Subject>("语文");
  const [data, setData] = useState<LocalTopicList | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<LocalTopicInfo | null>(null);
  const [deleting, setDeleting] = useState<LocalTopicInfo | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    if (!unlocked) {
      setData(null);
      return;
    }
    let active = true;
    setLoading(true);
    listLocalTopics(subject)
      .then((response) => {
        if (active) {
          setData(response);
          setError(null);
        }
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
  }, [unlocked, subject, refreshKey]);

  const refresh = () => setRefreshKey((value) => value + 1);

  async function confirmDelete() {
    if (!deleting || deleteBusy) {
      return;
    }
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      const response = await deleteLocalTopic(deleting.id);
      setNotice(
        `${response.id} 已删除；解绑错题 ${response.mistakes_unbound} 道、题库 ${response.problems_unbound} 道（历史记录仍在）`,
      );
      setDeleting(null);
      refresh();
    } catch (cause) {
      setDeleteError(errorMessage(cause));
    } finally {
      setDeleteBusy(false);
    }
  }

  if (!sessionLoading && !unlocked) {
    return (
      <Stack gap="md">
        <Title order={2}>学科 seed</Title>
        <Alert color="orange" variant="light" title="家长专属">
          本地知识点管理只对家长开放。请点右上角「家长区」解锁后再进入；
          未解锁时接口返回 403，孩子区不显示本页入口。
        </Alert>
      </Stack>
    );
  }

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center" wrap="wrap">
        <Title order={2}>学科 seed</Title>
        <Group gap="xs">
          <SegmentedControl
            size="xs"
            data={SUBJECTS.map((value) => ({ value, label: value }))}
            value={subject}
            onChange={(value) => {
              setNotice(null);
              setSubject(value as Subject);
            }}
          />
          {data && (
            <Text size="sm" c="dimmed">
              共 {data.total} 个本地点
            </Text>
          )}
          <Button size="compact-sm" variant="subtle" onClick={refresh}>
            刷新
          </Button>
          <Button size="compact-sm" onClick={() => setCreating(true)}>
            新增知识点
          </Button>
        </Group>
      </Group>

      <Alert color="blue" variant="light">
        仓库 seed（数学/英语/物理）只读；这里只管理语文（cnl_）与化学（cnc_）
        的家长自建章级知识点。文件真源在 `data/seeds_local/`，随备份走；
        SQLite 只是装载副本，重启后按文件恢复。
      </Alert>

      {notice && (
        <Alert
          color="green"
          variant="light"
          title="操作完成"
          withCloseButton
          onClose={() => setNotice(null)}
        >
          {notice}
        </Alert>
      )}

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
      {!loading && !error && data && data.items.length === 0 && (
        <Alert color="gray" variant="light" title={`还没有${subject}本地知识点`}>
          先建立章级知识点，才能在题库审核/错题核对里选到它；同一学科上限 200
          点，建议按教材章级收录 40–80 点。
        </Alert>
      )}

      {data?.items.map((item) => (
        <TopicCard
          key={item.id}
          item={item}
          onEdit={() => setEditing(item)}
          onDelete={() => {
            setDeleteError(null);
            setDeleting(item);
          }}
        />
      ))}

      {(creating || editing) && (
        <TopicFormModal
          key={editing?.id ?? `new-${subject}`}
          subject={subject}
          item={editing}
          onClose={() => {
            setCreating(false);
            setEditing(null);
          }}
          onSaved={(message) => {
            setNotice(message);
            refresh();
          }}
        />
      )}

      {deleting && (
        <Modal
          opened
          onClose={() => setDeleting(null)}
          title={`删除知识点 ${deleting.id}`}
          size="md"
        >
          <Stack gap="sm">
            <Alert color="red" variant="light" title="删除后果">
              将从 `seeds_local/topics_{deleting.subject}.json` 移除并删除
              knowledge_seed 行；引用它的错题与题库会解绑（主考点变空，错题仍保留，
              退回原题重做），历史 attempts / 事件不受影响。
            </Alert>
            <Text size="sm">
              {deleting.name}：将解绑错题 {deleting.mistake_count} 道、题库{" "}
              {deleting.problem_count} 道。
            </Text>
            {deleting.mistake_count > 0 || deleting.problem_count > 0 ? (
              <Alert color="orange" variant="light">
                仍有数据引用该考点，请确认这些错题/题目已无需归类，或先改挂到其他考点。
              </Alert>
            ) : null}
            {deleteError && (
              <Alert color="red" variant="light" title="删除失败">
                {deleteError}
              </Alert>
            )}
            <Group justify="flex-end">
              <Button
                variant="default"
                onClick={() => setDeleting(null)}
                disabled={deleteBusy}
              >
                取消
              </Button>
              <Button
                color="red"
                onClick={() => void confirmDelete()}
                loading={deleteBusy}
              >
                确认删除
              </Button>
            </Group>
          </Stack>
        </Modal>
      )}
    </Stack>
  );
}
