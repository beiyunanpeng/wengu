import {
  Alert,
  Badge,
  Button,
  Card,
  Grid,
  Group,
  Loader,
  Modal,
  Select,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { useEffect, useState } from "react";

import { errorMessage } from "../api/client";
import {
  approveBankDraft,
  createBankItem,
  listBankDrafts,
  listBankItems,
  rejectBankDraft,
  unvoidBankItem,
  updateBankItem,
  voidBankItem,
} from "../api/endpoints";
import type {
  BankChoice,
  BankDraft,
  BankDraftListResponse,
  BankItemInfo,
  BankItemListResponse,
} from "../api/types";
import CategoryPicker from "../components/CategoryPicker";
import MathText from "../components/MathText";
import { QuestionFigure } from "../components/QuizQuestionCard";
import { useParentSession } from "../parent/ParentSession";

const TYPE_LABELS: Record<string, string> = {
  choice: "选择",
  numeric: "数值",
  short: "短答",
  self: "解答",
};

const TYPE_OPTIONS = Object.entries(TYPE_LABELS).map(([value, label]) => ({
  value,
  label,
}));

const STATUS_LABELS: Record<string, string> = {
  draft: "待审核",
  approved: "已入库",
  rejected: "已驳回",
};

function statusColor(status: string): string {
  if (status === "approved") {
    return "green";
  }
  if (status === "rejected") {
    return "gray";
  }
  return "blue";
}

function splitLines(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function parseChoices(value: string): BankChoice[] {
  const choices: BankChoice[] = [];
  for (const line of splitLines(value)) {
    const separator = line.search(/[|｜]/);
    if (separator <= 0) {
      continue;
    }
    const key = line.slice(0, separator).trim();
    const text = line.slice(separator + 1).trim();
    if (key && text) {
      choices.push({ key, text });
    }
  }
  return choices;
}

function parseAcceptable(value: string): string[] {
  return value
    .split(/[,，、;；]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function DraftCard({
  draft,
  onReviewed,
}: {
  draft: BankDraft;
  onReviewed: (message: string, color: "green" | "orange" | "gray") => void;
}) {
  const [topicId, setTopicId] = useState<string | null>(draft.topic_id || null);
  const [answer, setAnswer] = useState(draft.answer);
  const [verify, setVerify] = useState(draft.verify);
  const [difficulty, setDifficulty] = useState(draft.difficulty);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reviewed = done || draft.status !== "draft";

  async function handleApprove() {
    if (busy || reviewed) {
      return;
    }
    if (!topicId) {
      setError("请先选择主考点（topic_id 必须存在于 knowledge_seed）");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await approveBankDraft(draft.id, {
        topic_id: topicId,
        answer,
        verify,
        difficulty,
      });
      setDone(true);
      onReviewed(
        `草稿 #${draft.id} 已入库 problem_bank #${response.problem_bank_id} · verify_status=${response.verify_status}`,
        response.verify_status === "verified" ? "green" : "orange",
      );
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  async function handleReject() {
    if (busy || reviewed) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await rejectBankDraft(draft.id);
      setDone(true);
      onReviewed(`草稿 #${draft.id} 已驳回，不会进入 problem_bank`, "gray");
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card withBorder>
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start" wrap="wrap">
          <Group gap="xs" wrap="wrap">
            <Badge variant="light">草稿 #{draft.id}</Badge>
            <Badge variant="outline">
              {TYPE_LABELS[draft.type] ?? draft.type}
            </Badge>
            {draft.subject && (
              <Badge variant="outline" color="gray">
                {draft.subject}
              </Badge>
            )}
            {draft.difficulty && (
              <Badge variant="outline" color="grape">
                {draft.difficulty}
              </Badge>
            )}
            {draft.has_placeholder && (
              <Badge color="red" variant="light">
                含占位符
              </Badge>
            )}
            <Badge color={statusColor(draft.status)} variant="light">
              {STATUS_LABELS[draft.status] ?? draft.status}
            </Badge>
          </Group>
          <Text size="xs" c="dimmed">
            {draft.filename || "来源未知"} · #{draft.seq}
            {draft.source_ref ? ` · ${draft.source_ref}` : ""}
          </Text>
        </Group>

        <Card withBorder padding="sm" bg="var(--mantine-color-gray-0)">
          <Text size="xs" c="dimmed" fw={600} mb={6}>
            题目（卷面原文）
          </Text>
          <MathText text={draft.prompt} />
          {draft.figure && <QuestionFigure svg={draft.figure} />}
          {draft.choices.length > 0 && (
            <Stack gap={4} mt="xs">
              {draft.choices.map((choice) => (
                <Group key={choice.key} gap="xs" align="flex-start" wrap="nowrap">
                  <Badge variant="outline" circle>
                    {choice.key}
                  </Badge>
                  <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
                    <MathText text={choice.text} />
                    {choice.figure && <QuestionFigure svg={choice.figure} />}
                  </Stack>
                </Group>
              ))}
            </Stack>
          )}
        </Card>

        <Text size="xs" c="dimmed">
          建议考点：
          {draft.topic_name
            ? `${draft.topic_name} · ${draft.topic_id}`
            : draft.topic_id || "未识别"}
        </Text>

        <CategoryPicker
          value={topicId}
          onChange={setTopicId}
          label="主考点（入库前必须有）"
          initialLabel={
            draft.topic_name ? `${draft.topic_name} · ${draft.subject}` : null
          }
        />

        <Grid gutter="sm">
          <Grid.Col span={{ base: 12, md: 7 }}>
            <TextInput
              label="标准答案（必填）"
              description="照片/答案册里没有答案时必须由家长补填；系统绝不自行解题生成"
              value={answer}
              onChange={(event) => setAnswer(event.currentTarget.value)}
              placeholder="例如 12"
              maxLength={1000}
              disabled={reviewed}
            />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 5 }}>
            <TextInput
              label="难度（可选）"
              value={difficulty}
              onChange={(event) => setDifficulty(event.currentTarget.value)}
              maxLength={40}
              disabled={reviewed}
            />
          </Grid.Col>
        </Grid>

        <TextInput
          label="verify 表达式（可选）"
          description="入库前会过 AST 白名单沙箱；禁止 import/赋值/属性访问，纯数值矛盾会拒绝入库"
          value={verify}
          onChange={(event) => setVerify(event.currentTarget.value)}
          placeholder="例如 3*4 或 x**2+1"
          maxLength={2000}
          disabled={reviewed}
        />

        <Group align="center" wrap="wrap">
          <Button onClick={() => void handleApprove()} loading={busy} disabled={reviewed}>
            通过并入本
          </Button>
          <Button
            variant="light"
            color="red"
            onClick={() => void handleReject()}
            loading={busy}
            disabled={reviewed}
          >
            驳回
          </Button>
          {reviewed && (
            <Text size="sm" c="dimmed">
              该草稿已处理，不再重复入库。
            </Text>
          )}
        </Group>

        {error && (
          <Alert color="red" variant="light" title="未通过闸门">
            {error}
          </Alert>
        )}
      </Stack>
    </Card>
  );
}

function ManualEntryForm({ onCreated }: { onCreated: () => void }) {
  const [topicId, setTopicId] = useState<string | null>(null);
  const [type, setType] = useState<string>("numeric");
  const [difficulty, setDifficulty] = useState("");
  const [prompt, setPrompt] = useState("");
  const [answer, setAnswer] = useState("");
  const [acceptable, setAcceptable] = useState("");
  const [verify, setVerify] = useState("");
  const [choicesText, setChoicesText] = useState("");
  const [sourceRef, setSourceRef] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{
    problem_bank_id: number;
    verify_status: string;
  } | null>(null);

  async function submit() {
    if (busy) {
      return;
    }
    if (!topicId) {
      setError("请选择主考点");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await createBankItem({
        topic_id: topicId,
        type: type as "choice" | "numeric" | "short" | "self",
        difficulty,
        prompt,
        answer,
        acceptable: parseAcceptable(acceptable),
        verify,
        choices: parseChoices(choicesText),
        source_ref: sourceRef,
      });
      setResult({
        problem_bank_id: response.problem_bank_id,
        verify_status: response.verify_status,
      });
      setPrompt("");
      setAnswer("");
      setAcceptable("");
      setVerify("");
      setChoicesText("");
      setSourceRef("");
      onCreated();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card withBorder>
      <Stack gap="sm">
        <Title order={4}>手填直录（无外部转录时的兜底）</Title>
        <Text size="xs" c="dimmed">
          与队列审核共用同一闸门：必填题目/答案/考点，verify 过 AST 沙箱；
          题库只进 SQLite，不写 seed JSON。
        </Text>

        <Grid gutter="sm">
          <Grid.Col span={{ base: 12, md: 5 }}>
            <CategoryPicker
              value={topicId}
              onChange={setTopicId}
              label="主考点"
              required
            />
          </Grid.Col>
          <Grid.Col span={{ base: 6, md: 3 }}>
            <Select
              label="题型"
              data={TYPE_OPTIONS}
              value={type}
              onChange={(value) => setType(value ?? "numeric")}
              allowDeselect={false}
            />
          </Grid.Col>
          <Grid.Col span={{ base: 6, md: 4 }}>
            <TextInput
              label="难度（可选）"
              value={difficulty}
              onChange={(event) => setDifficulty(event.currentTarget.value)}
              maxLength={40}
            />
          </Grid.Col>
        </Grid>

        <Textarea
          label="题目"
          value={prompt}
          onChange={(event) => setPrompt(event.currentTarget.value)}
          placeholder="粘贴卷面原文；公式可用 $...$"
          minRows={2}
          maxLength={2000}
        />

        <Grid gutter="sm">
          <Grid.Col span={{ base: 12, md: 6 }}>
            <TextInput
              label="标准答案（必填）"
              value={answer}
              onChange={(event) => setAnswer(event.currentTarget.value)}
              maxLength={500}
            />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 6 }}>
            <TextInput
              label="可接受答案（逗号分隔，可选）"
              value={acceptable}
              onChange={(event) => setAcceptable(event.currentTarget.value)}
            />
          </Grid.Col>
        </Grid>

        <TextInput
          label="verify 表达式（可选）"
          value={verify}
          onChange={(event) => setVerify(event.currentTarget.value)}
          placeholder="例如 3*4 或 x**2+1"
          maxLength={2000}
        />

        <Textarea
          label="选择题选项（每行 A|选项文字；仅选择题需要）"
          value={choicesText}
          onChange={(event) => setChoicesText(event.currentTarget.value)}
          placeholder={"A|3\nB|4\nC|5\nD|6"}
          minRows={2}
        />

        <TextInput
          label="出处（可选）"
          value={sourceRef}
          onChange={(event) => setSourceRef(event.currentTarget.value)}
          maxLength={200}
        />

        <Group>
          <Button onClick={() => void submit()} loading={busy}>
            直接入库
          </Button>
        </Group>

        {error && (
          <Alert color="red" variant="light" title="未通过闸门">
            {error}
          </Alert>
        )}
        {result && (
          <Alert
            color={result.verify_status === "verified" ? "green" : "orange"}
            variant="light"
            title="已入库"
          >
            <Text size="sm">
              problem_bank #{result.problem_bank_id} · verify_status=
              {result.verify_status}
            </Text>
          </Alert>
        )}
      </Stack>
    </Card>
  );
}

function VerifyBadge({ status }: { status: string }) {
  if (status === "verified") {
    return (
      <Badge color="green" variant="light">
        verify 已核验
      </Badge>
    );
  }
  return (
    <Badge color="orange" variant="light">
      未经核验
    </Badge>
  );
}

function BankItemCard({
  item,
  busy,
  onEdit,
  onToggle,
}: {
  item: BankItemInfo;
  busy: boolean;
  onEdit: () => void;
  onToggle: () => void;
}) {
  const voided = item.status === "voided";
  return (
    <Card withBorder style={{ opacity: voided ? 0.72 : 1 }}>
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start" wrap="wrap">
          <Group gap="xs" wrap="wrap">
            <Badge variant="light">#{item.id}</Badge>
            {item.type && (
              <Badge variant="outline">
                {TYPE_LABELS[item.type] ?? item.type}
              </Badge>
            )}
            <Badge variant="outline" color="gray">
              {item.subject}
            </Badge>
            {item.difficulty && (
              <Badge variant="outline" color="grape">
                {item.difficulty}
              </Badge>
            )}
            <VerifyBadge status={item.verify_status} />
            <Badge color={voided ? "red" : "teal"} variant="light">
              {voided ? "已作废" : "在用"}
            </Badge>
          </Group>
          <Text size="xs" c="dimmed">
            {item.external_id}
          </Text>
        </Group>

        {voided && (
          <Alert color="red" variant="light" title="已退出考核出题">
            该题不在运行时检索池中；历史 attempts / 事件与已出过的卷子不受影响。
          </Alert>
        )}

        <Card withBorder padding="sm" bg="var(--mantine-color-gray-0)">
          <MathText text={item.prompt} />
          {item.figure && <QuestionFigure svg={item.figure} />}
          {item.choices.length > 0 && (
            <Stack gap={4} mt="xs">
              {item.choices.map((choice) => (
                <Group
                  key={choice.key}
                  gap="xs"
                  align="flex-start"
                  wrap="nowrap"
                >
                  <Badge variant="outline" circle>
                    {choice.key}
                  </Badge>
                  <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
                    <MathText text={choice.text} />
                    {choice.figure && <QuestionFigure svg={choice.figure} />}
                  </Stack>
                </Group>
              ))}
            </Stack>
          )}
        </Card>

        <Group gap="lg" wrap="wrap">
          <Text size="sm" fw={600}>
            标准答案：{item.answer}
          </Text>
          {item.acceptable.length > 0 && (
            <Text size="sm" c="dimmed">
              可接受：{item.acceptable.join("、")}
            </Text>
          )}
          {item.unordered && (
            <Badge variant="outline" color="gray">
              答案无序
            </Badge>
          )}
        </Group>
        {item.verify && (
          <Text size="xs" c="dimmed">
            verify：{item.verify}
          </Text>
        )}

        <Group justify="space-between" align="center" wrap="wrap">
          <Text size="xs" c="dimmed">
            {item.topic_name
              ? `${item.topic_name} · ${item.topic_id}`
              : item.topic_id || "未挂考点"}
            {item.updated_at ? ` · 更新于 ${item.updated_at}` : ""}
          </Text>
          <Group gap="xs">
            <Button size="compact-sm" variant="light" onClick={onEdit} disabled={busy}>
              编辑
            </Button>
            <Button
              size="compact-sm"
              variant="light"
              color={voided ? "green" : "red"}
              onClick={onToggle}
              loading={busy}
            >
              {voided ? "撤销作废" : "作废"}
            </Button>
          </Group>
        </Group>
      </Stack>
    </Card>
  );
}

function BankItemEditModal({
  item,
  onClose,
  onSaved,
}: {
  item: BankItemInfo;
  onClose: () => void;
  onSaved: (message: string, color: "green" | "orange") => void;
}) {
  const [topicId, setTopicId] = useState<string | null>(item.topic_id);
  const [type, setType] = useState<string>(item.type ?? "numeric");
  const [difficulty, setDifficulty] = useState(item.difficulty ?? "");
  const [prompt, setPrompt] = useState(item.prompt);
  const [answer, setAnswer] = useState(item.answer);
  const [acceptable, setAcceptable] = useState(item.acceptable.join(", "));
  const [unordered, setUnordered] = useState(item.unordered);
  const [verify, setVerify] = useState(item.verify);
  const [choicesText, setChoicesText] = useState(
    item.choices.map((choice) => `${choice.key}|${choice.text}`).join("\n"),
  );
  const [figure, setFigure] = useState(item.figure ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    if (busy) {
      return;
    }
    if (!topicId) {
      setError("请选择主考点（topic_id 必须存在于 knowledge_seed）");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const originalFigures = new Map(
        item.choices.map((choice) => [choice.key, choice.figure ?? null]),
      );
      const choices =
        type === "choice"
          ? parseChoices(choicesText).map((choice) => ({
              ...choice,
              figure: originalFigures.get(choice.key) ?? null,
            }))
          : [];
      const response = await updateBankItem(item.id, {
        topic_id: topicId,
        type: type as "choice" | "numeric" | "short" | "self",
        difficulty,
        prompt,
        answer,
        acceptable: parseAcceptable(acceptable),
        unordered,
        verify,
        choices,
        figure: figure.trim() ? figure : null,
      });
      onSaved(
        `problem_bank #${item.id} 已更新 · verify_status=${response.verify_status}`,
        response.verify_status === "verified" ? "green" : "orange",
      );
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
      title={`编辑 problem_bank #${item.id}`}
      size="lg"
    >
      <Stack gap="sm">
        <Alert color="blue" variant="light">
          编辑不改 external_id，历史 attempts / 事件与判分不回溯；保存前会重跑同一套审核闸门。
        </Alert>
        {item.status === "voided" && (
          <Alert color="red" variant="light">
            该题当前已作废，编辑不会自动恢复；需要时请另行「撤销作废」。
          </Alert>
        )}

        <Grid gutter="sm">
          <Grid.Col span={{ base: 12, md: 5 }}>
            <CategoryPicker
              value={topicId}
              onChange={setTopicId}
              label="主考点"
              required
              initialLabel={
                item.topic_name ? `${item.topic_name} · ${item.subject}` : null
              }
            />
          </Grid.Col>
          <Grid.Col span={{ base: 6, md: 3 }}>
            <Select
              label="题型"
              data={TYPE_OPTIONS}
              value={type}
              onChange={(value) => setType(value ?? "numeric")}
              allowDeselect={false}
            />
          </Grid.Col>
          <Grid.Col span={{ base: 6, md: 4 }}>
            <TextInput
              label="难度（可选）"
              value={difficulty}
              onChange={(event) => setDifficulty(event.currentTarget.value)}
              maxLength={40}
            />
          </Grid.Col>
        </Grid>

        <Textarea
          label="题目"
          value={prompt}
          onChange={(event) => setPrompt(event.currentTarget.value)}
          minRows={2}
          maxLength={2000}
        />

        <Grid gutter="sm">
          <Grid.Col span={{ base: 12, md: 6 }}>
            <TextInput
              label="标准答案（必填）"
              value={answer}
              onChange={(event) => setAnswer(event.currentTarget.value)}
              maxLength={500}
            />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 6 }}>
            <TextInput
              label="可接受答案（逗号分隔，可选）"
              value={acceptable}
              onChange={(event) => setAcceptable(event.currentTarget.value)}
            />
          </Grid.Col>
        </Grid>

        <Switch
          label="答案无序（多答案不区分顺序）"
          checked={unordered}
          onChange={(event) => setUnordered(event.currentTarget.checked)}
        />

        <TextInput
          label="verify 表达式（可选）"
          description="保存前会过 AST 白名单沙箱；纯数值矛盾会拒绝保存"
          value={verify}
          onChange={(event) => setVerify(event.currentTarget.value)}
          maxLength={2000}
        />

        <Textarea
          label="选择题选项（每行 A|选项文字；仅选择题需要）"
          value={choicesText}
          onChange={(event) => setChoicesText(event.currentTarget.value)}
          placeholder={"A|3\nB|4\nC|5\nD|6"}
          minRows={2}
        />

        <Textarea
          label="题图 SVG（可选，留空即清除）"
          description="内联 SVG 会先过净化再渲染"
          value={figure}
          onChange={(event) => setFigure(event.currentTarget.value)}
          minRows={2}
          autosize
        />

        {error && (
          <Alert color="red" variant="light" title="未通过闸门">
            {error}
          </Alert>
        )}

        <Group justify="flex-end">
          <Button variant="default" onClick={onClose} disabled={busy}>
            取消
          </Button>
          <Button onClick={() => void save()} loading={busy}>
            保存修改
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function BankItemsBoard({
  signal,
  onNotice,
}: {
  signal: number;
  onNotice: (message: string, color: "green" | "orange" | "gray") => void;
}) {
  const [status, setStatus] = useState<"active" | "voided" | "all">("active");
  const [topicId, setTopicId] = useState<string | null>(null);
  const [data, setData] = useState<BankItemListResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [editing, setEditing] = useState<BankItemInfo | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    listBankItems({
      status,
      topic_id: topicId ?? undefined,
      limit: 200,
    })
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
  }, [status, topicId, refreshKey, signal]);

  const refresh = () => setRefreshKey((value) => value + 1);

  async function toggle(item: BankItemInfo) {
    if (busyId !== null) {
      return;
    }
    setBusyId(item.id);
    setError(null);
    try {
      const response =
        item.status === "active"
          ? await voidBankItem(item.id)
          : await unvoidBankItem(item.id);
      onNotice(
        response.status === "voided"
          ? `problem_bank #${item.id} 已作废，退出考核出题池（历史记录不变）`
          : `problem_bank #${item.id} 已恢复，重新进入考核出题池`,
        response.status === "voided" ? "gray" : "green",
      );
      refresh();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <Card withBorder>
      <Stack gap="sm">
        <Group justify="space-between" align="center" wrap="wrap">
          <Title order={4}>已入库题目（可修订）</Title>
          <Group gap="xs" wrap="wrap">
            <Select
              size="xs"
              data={[
                { value: "active", label: "在用" },
                { value: "voided", label: "已作废" },
                { value: "all", label: "全部" },
              ]}
              value={status}
              onChange={(value) =>
                setStatus((value ?? "active") as "active" | "voided" | "all")
              }
              allowDeselect={false}
              w={110}
            />
            {data && (
              <Text size="sm" c="dimmed">
                共 {data.total} 条
              </Text>
            )}
            <Button size="compact-sm" variant="subtle" onClick={refresh}>
              刷新
            </Button>
          </Group>
        </Group>

        <CategoryPicker
          value={topicId}
          onChange={setTopicId}
          label="按考点筛选"
          placeholder="输入关键词筛选已入库题目"
        />

        <Alert color="blue" variant="light">
          编辑会重跑同一套闸门（必填 / 占位 / AST 沙箱 / 选项 key / 数值矛盾）；
          作废只退出检索池，不删题、不改写历史 attempts 与事件。
        </Alert>

        {loading && (
          <Group justify="center" py="md">
            <Loader size="sm" />
          </Group>
        )}
        {error && (
          <Alert color="red" variant="light" title="操作失败">
            {error}
          </Alert>
        )}
        {!loading && !error && data && data.items.length === 0 && (
          <Alert color="gray" variant="light" title="当前筛选下没有已入库题目">
            通过审核草稿或手填直录后，题目会出现在这里，可继续编辑或作废。
          </Alert>
        )}

        {data?.items.map((item) => (
          <BankItemCard
            key={item.id}
            item={item}
            busy={busyId === item.id}
            onEdit={() => setEditing(item)}
            onToggle={() => void toggle(item)}
          />
        ))}
      </Stack>

      {editing && (
        <BankItemEditModal
          key={editing.id}
          item={editing}
          onClose={() => setEditing(null)}
          onSaved={(message, color) => {
            onNotice(message, color);
            refresh();
          }}
        />
      )}
    </Card>
  );
}

export default function BankPage() {
  const { unlocked, loading: sessionLoading } = useParentSession();
  const [status, setStatus] = useState<string>("draft");
  const [data, setData] = useState<BankDraftListResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{
    text: string;
    color: "green" | "orange" | "gray";
  } | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    if (!unlocked) {
      setData(null);
      return;
    }
    let active = true;
    setLoading(true);
    listBankDrafts({
      status: status as "draft" | "approved" | "rejected" | "all",
      limit: 100,
    })
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
  }, [unlocked, status, refreshKey]);

  const refresh = () => setRefreshKey((value) => value + 1);

  const handleReviewed = (
    message: string,
    color: "green" | "orange" | "gray",
  ) => {
    setNotice({ text: message, color });
    refresh();
  };

  if (!sessionLoading && !unlocked) {
    return (
      <Stack gap="md">
        <Title order={2}>题库审核</Title>
        <Alert color="orange" variant="light" title="家长专属">
          题库审核只对家长开放。请点右上角「家长区」解锁后再进入；未解锁时接口返回
          403，孩子区不显示本页入口。
        </Alert>
      </Stack>
    );
  }

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center" wrap="wrap">
        <Title order={2}>题库审核</Title>
        <Group gap="xs">
          <Select
            size="xs"
            data={[
              { value: "draft", label: "待审核" },
              { value: "approved", label: "已入库" },
              { value: "rejected", label: "已驳回" },
              { value: "all", label: "全部" },
            ]}
            value={status}
            onChange={(value) => setStatus(value ?? "draft")}
            allowDeselect={false}
            w={120}
          />
          {data && (
            <Text size="sm" c="dimmed">
              共 {data.total} 条
            </Text>
          )}
          <Button size="compact-sm" variant="subtle" onClick={refresh}>
            刷新
          </Button>
        </Group>
      </Group>

      <Alert color="blue" variant="light">
        外部 agent 转录的空白真题只停在这里；确认后才写进 problem_bank。
        答案必须来自卷面/答案册或家长补填——系统不会自行解题生成标准答案；
        verify 表达式过 AST 沙箱，纯数值矛盾拒绝入库。
      </Alert>

      {notice && (
        <Alert
          color={notice.color}
          variant="light"
          title="审核结果（入库题固定标记未经教师审核 / 未经二遍复核）"
          withCloseButton
          onClose={() => setNotice(null)}
        >
          {notice.text}
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
        <Alert color="gray" variant="light" title="没有对应状态的录题草稿">
          把外部 agent 按 `doubao_bank_transcribe_v1` 模板转录的 JSON
          放进 inbox 监听目录，或直接使用下方手填表单。
        </Alert>
      )}

      {data?.items.map((draft) => (
        <DraftCard key={draft.id} draft={draft} onReviewed={handleReviewed} />
      ))}

      <BankItemsBoard signal={refreshKey} onNotice={handleReviewed} />

      <ManualEntryForm onCreated={refresh} />
    </Stack>
  );
}
