import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Divider,
  FileInput,
  Group,
  Loader,
  Progress,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { errorMessage } from "../api/client";
import {
  addRecitationCandidates,
  createDictationSheet,
  createRecitation,
  getDashboard,
  getDictationSheet,
  getDueRecitations,
  importRecitations,
  listDictationSheets,
  listRecitationCandidates,
  listRecitations,
  recordDictationResults,
  reviewRecitation,
  updateRecitation,
} from "../api/endpoints";
import type {
  DictationResultsResponse,
  DictationSheet,
  DictationSheetDetail,
  RecitationCandidate,
  RecitationCandidateBatchResponse,
  RecitationDueItem,
  RecitationDueResponse,
  RecitationImportResponse,
  RecitationItem,
  RecitationListResponse,
  RecitationVerdict,
} from "../api/types";
import { toISODate } from "../lib/dates";
import { useParentSession } from "../parent/ParentSession";

const IMPORT_SUBJECTS = [
  "英语",
  "语文",
  "历史",
  "道德与法治",
  "道法",
  "生物",
  "地理",
];

export default function RecitationsPage() {
  const { unlocked } = useParentSession();
  const navigate = useNavigate();
  const [due, setDue] = useState<RecitationDueResponse | null>(null);
  const [items, setItems] = useState<RecitationListResponse | null>(null);
  const [progress, setProgress] = useState<{ today: number; limit: number } | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [lastResult, setLastResult] = useState<string | null>(null);
  const [revealed, setRevealed] = useState<Record<number, boolean>>({});

  const [subject, setSubject] = useState("英语");
  const [prompt, setPrompt] = useState("");
  const [answer, setAnswer] = useState("");
  const [unit, setUnit] = useState("");
  const [adding, setAdding] = useState(false);

  const [importSubject, setImportSubject] = useState("英语");
  const [importText, setImportText] = useState("");
  const [importFileName, setImportFileName] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [importReport, setImportReport] =
    useState<RecitationImportResponse | null>(null);

  const [candidates, setCandidates] = useState<RecitationCandidate[]>([]);
  const [candidateLoading, setCandidateLoading] = useState(false);
  const [selectedWords, setSelectedWords] = useState<string[]>([]);
  const [candidateUnit, setCandidateUnit] = useState("");
  const [candidateBusy, setCandidateBusy] = useState(false);
  const [candidateReport, setCandidateReport] =
    useState<RecitationCandidateBatchResponse | null>(null);
  const [batchIds, setBatchIds] = useState<number[]>([]);
  const [undoingBatch, setUndoingBatch] = useState(false);

  const [sheetSelection, setSheetSelection] = useState<number[]>([]);
  const [creatingSheet, setCreatingSheet] = useState(false);
  const [sheets, setSheets] = useState<DictationSheet[]>([]);
  const [recording, setRecording] = useState<DictationSheetDetail | null>(null);
  const [verdicts, setVerdicts] = useState<Record<number, RecitationVerdict>>({});
  const [recordingBusy, setRecordingBusy] = useState(false);
  const [recordReport, setRecordReport] =
    useState<DictationResultsResponse | null>(null);

  async function load(showSpinner = true) {
    if (showSpinner) {
      setLoading(true);
    }
    try {
      const today = toISODate(new Date());
      const [dueResponse, listResponse, dashboard] = await Promise.all([
        getDueRecitations(today),
        listRecitations({ limit: 200 }),
        getDashboard({ today }),
      ]);
      setDue(dueResponse);
      setItems(listResponse);
      setProgress({
        today: dashboard.recitations_today,
        limit: dashboard.recitation_limit,
      });
      setError(null);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (unlocked) {
      void loadCandidates();
      void loadSheets();
    } else {
      setCandidates([]);
      setSelectedWords([]);
      setCandidateReport(null);
      setBatchIds([]);
      setSheets([]);
      setSheetSelection([]);
      setRecording(null);
      setVerdicts({});
      setRecordReport(null);
    }
  }, [unlocked]);

  async function mark(itemId: number, verdict: RecitationVerdict) {
    if (busyId !== null) {
      return;
    }
    setBusyId(itemId);
    setActionError(null);
    setLastResult(null);
    try {
      const result = await reviewRecitation(itemId, { verdict });
      setLastResult(
        result.graduated
          ? `「${result.item.prompt}」已背熟并毕业，不用再排期。`
          : `「${result.item.prompt}」下次复习：${result.scheduled_next ?? "—"}（第 ${result.rung + 1} 档）`,
      );
      await load(false);
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setBusyId(null);
    }
  }

  async function addItem() {
    if (adding) {
      return;
    }
    if (!subject.trim() || !prompt.trim()) {
      setActionError("请填写学科与背诵条目");
      return;
    }
    setAdding(true);
    setActionError(null);
    try {
      await createRecitation({
        subject: subject.trim(),
        prompt: prompt.trim(),
        answer: answer.trim() || null,
        unit: unit.trim() || null,
      });
      setPrompt("");
      setAnswer("");
      setUnit("");
      await load(false);
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setAdding(false);
    }
  }

  async function pickImportFile(file: File | null) {
    if (!file) {
      return;
    }
    setActionError(null);
    try {
      setImportText(await file.text());
      setImportFileName(file.name);
    } catch {
      setActionError("读取文件失败，请重试或改为粘贴文本");
    }
  }

  async function runImport() {
    if (importing) {
      return;
    }
    if (!importText.trim()) {
      setActionError("请先选择 CSV/TSV 文件或粘贴词表文本");
      return;
    }
    setImporting(true);
    setActionError(null);
    setImportReport(null);
    try {
      const report = await importRecitations({
        subject: importSubject,
        text: importText,
      });
      setImportReport(report);
      await load(false);
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setImporting(false);
    }
  }

  async function loadCandidates() {
    if (!unlocked) {
      return;
    }
    setCandidateLoading(true);
    try {
      const rows = await listRecitationCandidates(50);
      setCandidates(rows);
      setSelectedWords((current) =>
        current.filter((word) => rows.some((row) => row.word === word)),
      );
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setCandidateLoading(false);
    }
  }

  async function addSelectedCandidates() {
    if (candidateBusy || selectedWords.length === 0) {
      return;
    }
    setCandidateBusy(true);
    setActionError(null);
    setCandidateReport(null);
    try {
      const report = await addRecitationCandidates({
        words: selectedWords,
        unit: candidateUnit.trim() || null,
      });
      setCandidateReport(report);
      setBatchIds(report.created.map((item) => item.id));
      setSelectedWords([]);
      setCandidateUnit("");
      await load(false);
      await loadCandidates();
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setCandidateBusy(false);
    }
  }

  async function undoBatch() {
    if (undoingBatch || batchIds.length === 0) {
      return;
    }
    setUndoingBatch(true);
    setActionError(null);
    try {
      for (const id of batchIds) {
        await updateRecitation(id, { status: "retired" });
      }
      setLastResult(`已停用本批 ${batchIds.length} 条背诵条目。`);
      setBatchIds([]);
      await load(false);
      await loadCandidates();
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setUndoingBatch(false);
    }
  }

  async function toggleStatus(item: RecitationItem) {
    if (busyId !== null) {
      return;
    }
    setBusyId(item.id);
    setActionError(null);
    try {
      await updateRecitation(item.id, {
        status: item.status === "active" ? "retired" : "active",
      });
      await load(false);
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setBusyId(null);
    }
  }

  async function loadSheets() {
    try {
      const response = await listDictationSheets("open");
      setSheets(response.items);
    } catch (cause) {
      setActionError(errorMessage(cause));
    }
  }

  async function generateSheet() {
    if (creatingSheet || sheetSelection.length === 0) {
      return;
    }
    setCreatingSheet(true);
    setActionError(null);
    try {
      const ordered = (items?.items ?? [])
        .filter(
          (item) =>
            item.status === "active" && sheetSelection.includes(item.id),
        )
        .map((item) => item.id);
      const detail = await createDictationSheet({ item_ids: ordered });
      setSheetSelection([]);
      await loadSheets();
      navigate(`/print/dictation?sheet_id=${detail.sheet.id}`);
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setCreatingSheet(false);
    }
  }

  async function openRecording(sheetId: number) {
    setActionError(null);
    setRecordReport(null);
    try {
      const detail = await getDictationSheet(sheetId);
      setRecording(detail);
      setVerdicts({});
    } catch (cause) {
      setActionError(errorMessage(cause));
    }
  }

  async function submitRecording() {
    if (!recording || recordingBusy) {
      return;
    }
    const entries = recording.items
      .filter((item) => verdicts[item.item_id] !== undefined)
      .map((item) => ({
        item_id: item.item_id,
        verdict: verdicts[item.item_id],
      }));
    if (entries.length === 0) {
      setActionError("请先按卷面词序逐词勾选 对/错，再批量回录。");
      return;
    }
    setRecordingBusy(true);
    setActionError(null);
    try {
      const report = await recordDictationResults(recording.sheet.id, {
        results: entries,
      });
      setRecordReport(report);
      setRecording(null);
      setVerdicts({});
      await load(false);
      await loadSheets();
    } catch (cause) {
      setActionError(errorMessage(cause));
    } finally {
      setRecordingBusy(false);
    }
  }

  const activeItems = (items?.items ?? []).filter(
    (item) => item.status === "active",
  );

  const goal = progress?.limit ?? 0;
  const todayDone = progress?.today ?? 0;

  return (
    <Stack gap="md">
      <Stack gap={4}>
        <Title order={2}>英语背诵</Title>
        <Text size="sm" c="dimmed">
          家长手动录入条目，孩子按记忆阶梯自评（1/3/7/14/30 天）。
          “记得”进一档，“没记住”保持当前档；背诵不是错题，也不计入掌握度。
        </Text>
      </Stack>

      {actionError && (
        <Alert color="red" variant="light">
          {actionError}
        </Alert>
      )}
      {lastResult && (
        <Alert color="teal" variant="light">
          {lastResult}
        </Alert>
      )}
      {error && (
        <Alert color="red" variant="light" title="加载失败">
          {error}
        </Alert>
      )}

      {loading ? (
        <Group justify="center" py="xl">
          <Loader />
        </Group>
      ) : (
        <>
          <Card withBorder>
            <Stack gap="sm">
              <Group justify="space-between" align="center" wrap="wrap">
                <Text fw={600}>今日背诵</Text>
                <Text size="sm" c="dimmed">
                  {todayDone}/{goal} 已完成 · 今日到期 {due?.due_total ?? 0} 条
                </Text>
              </Group>
              <Progress
                value={goal > 0 ? Math.min(100, (todayDone / goal) * 100) : 0}
                color={goal > 0 && todayDone >= goal ? "teal" : "blue"}
                radius="xl"
                aria-label={`今日背诵进度 ${todayDone}/${goal}`}
              />
              {due && due.due_total === 0 ? (
                <Text size="sm" c="dimmed">
                  今天没有到期条目。新录入的条目当天就会出现。
                </Text>
              ) : (
                <Text size="xs" c="dimmed">
                  先背，再点“记得 / 没记住”；同一天重复点不会重复计数。
                </Text>
              )}
            </Stack>
          </Card>

          {due?.items.map((entry: RecitationDueItem) => {
            const shown = revealed[entry.item.id] ?? false;
            return (
              <Card key={entry.item.id} withBorder>
                <Stack gap="sm">
                  <Group justify="space-between" align="flex-start" wrap="wrap">
                    <Group gap="xs" wrap="wrap">
                      <Badge variant="light">{entry.item.subject}</Badge>
                      {entry.item.unit && (
                        <Badge color="gray" variant="light">
                          {entry.item.unit}
                        </Badge>
                      )}
                      <Badge color="grape" variant="light">
                        第 {entry.rung + 1} 档
                      </Badge>
                    </Group>
                    <Text size="xs" c="dimmed">
                      {entry.reviewed_on
                        ? `上次自评 ${entry.reviewed_on}`
                        : "新条目"}
                    </Text>
                  </Group>
                  <Text size="lg" fw={600} style={{ whiteSpace: "pre-wrap" }}>
                    {entry.item.prompt}
                  </Text>
                  {entry.item.answer && (
                    <Group gap="xs" align="center" wrap="wrap">
                      <Button
                        size="compact-xs"
                        variant="subtle"
                        onClick={() =>
                          setRevealed((current) => ({
                            ...current,
                            [entry.item.id]: !shown,
                          }))
                        }
                      >
                        {shown ? "收起答案" : "看答案"}
                      </Button>
                      {shown && (
                        <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
                          {entry.item.answer}
                        </Text>
                      )}
                    </Group>
                  )}
                  <Group gap="xs">
                    <Button
                      color="teal"
                      onClick={() => void mark(entry.item.id, "remembered")}
                      loading={busyId === entry.item.id}
                      disabled={busyId !== null}
                    >
                      记得
                    </Button>
                    <Button
                      color="orange"
                      variant="light"
                      onClick={() => void mark(entry.item.id, "forgot")}
                      loading={busyId === entry.item.id}
                      disabled={busyId !== null}
                    >
                      没记住
                    </Button>
                  </Group>
                </Stack>
              </Card>
            );
          })}

          <Divider my="sm" />

          {!unlocked && (
            <Alert color="gray" variant="light" title="条目维护属于家长操作">
              在右上角「家长区」输入 PIN 解锁后可新增、编辑或停用背诵条目；
              孩子的今日卡片不受影响。
            </Alert>
          )}

          {unlocked && (
            <Card withBorder>
              <Stack gap="sm">
                <Group justify="space-between" align="center" wrap="wrap">
                  <Text fw={600}>家长维护</Text>
                  <Text size="xs" c="dimmed">
                    同科同条目唯一；停用后不再出现在今日卡片
                  </Text>
                </Group>
                <SimpleGrid cols={{ base: 1, sm: 2, md: 4 }}>
                  <TextInput
                    label="学科"
                    value={subject}
                    onChange={(event) => setSubject(event.currentTarget.value)}
                    placeholder="英语"
                  />
                  <TextInput
                    label="背诵条目"
                    value={prompt}
                    onChange={(event) => setPrompt(event.currentTarget.value)}
                    placeholder="abandon"
                  />
                  <TextInput
                    label="答案（可选）"
                    value={answer}
                    onChange={(event) => setAnswer(event.currentTarget.value)}
                    placeholder="放弃"
                  />
                  <TextInput
                    label="单元（可选）"
                    value={unit}
                    onChange={(event) => setUnit(event.currentTarget.value)}
                    placeholder="Unit 1"
                  />
                </SimpleGrid>
                <Group>
                  <Button
                    onClick={() => void addItem()}
                    loading={adding}
                    disabled={!subject.trim() || !prompt.trim()}
                  >
                    添加条目
                  </Button>
                </Group>

                <Divider
                  my="xs"
                  label="批量导入（CSV / TSV）"
                  labelPosition="left"
                />
                <Group align="flex-end" gap="sm" wrap="wrap">
                  <Select
                    label="导入到学科"
                    data={IMPORT_SUBJECTS}
                    value={importSubject}
                    onChange={(value) => setImportSubject(value ?? "英语")}
                    allowDeselect={false}
                    w={160}
                  />
                  <FileInput
                    label="选择文件"
                    placeholder=".csv / .tsv / .txt"
                    accept=".csv,.tsv,.txt,text/csv,text/tab-separated-values,text/plain"
                    value={null}
                    onChange={(file) => void pickImportFile(file)}
                    w={240}
                  />
                  <Button
                    variant="light"
                    onClick={() => void runImport()}
                    loading={importing}
                  >
                    导入词表
                  </Button>
                </Group>
                <Textarea
                  label="或直接粘贴词表"
                  description="每行 prompt, answer, unit；首行表头可省略。空行与 # 开头的注释行会跳过。选择文件会覆盖此处文本。"
                  placeholder={"prompt,answer,unit\nabandon,放弃,Unit 1"}
                  value={importText}
                  onChange={(event) => {
                    setImportText(event.currentTarget.value);
                    setImportFileName(null);
                  }}
                  autosize
                  minRows={3}
                  maxRows={10}
                />
                <Text size="xs" c="dimmed">
                  只能导入 UTF-8 文本：Excel 请用“CSV UTF-8”导出，记事本另存为
                  UTF-8；GBK/ANSI 会乱码并被整批拒绝。
                </Text>
                {importFileName && (
                  <Text size="xs">已读取文件：{importFileName}</Text>
                )}
                {importReport && (
                  <Alert
                    color={importReport.errors.length > 0 ? "yellow" : "teal"}
                    variant="light"
                    title={`导入完成：成功 ${importReport.imported} 条`}
                  >
                    <Stack gap={4}>
                      <Text size="sm">
                        重复 {importReport.duplicates.length} 条（未覆盖已有条目）
                        {importReport.duplicates.length > 0
                          ? `：${importReport.duplicates
                              .slice(0, 5)
                              .map((row) => `${row.prompt}（第 ${row.line} 行）`)
                              .join("、")}${
                              importReport.duplicates.length > 5 ? " 等" : ""
                            }`
                          : ""}
                      </Text>
                      {importReport.errors.map((issue) => (
                        <Text
                          key={`${issue.line}-${issue.field ?? "none"}`}
                          size="sm"
                        >
                          第 {issue.line} 行
                          {issue.field ? `（${issue.field}）` : ""}：{issue.reason}
                        </Text>
                      ))}
                      {importReport.errors.length === 0 && (
                        <Text size="sm">没有坏行。</Text>
                      )}
                    </Stack>
                  </Alert>
                )}

                <Divider
                  my="xs"
                  label="从错题抽词（英语）"
                  labelPosition="left"
                />
                <Group justify="space-between" align="center" wrap="wrap">
                  <Text size="sm" c="dimmed">
                    来自 active 英语错题的当前题面，按出现错题数排序；每次现算，
                    不会自动入库。勾选后才会写入背诵池。
                  </Text>
                  <Button
                    size="compact-sm"
                    variant="subtle"
                    onClick={() => void loadCandidates()}
                    loading={candidateLoading}
                  >
                    刷新候选
                  </Button>
                </Group>
                {candidates.length === 0 ? (
                  <Text size="sm" c="dimmed">
                    暂无新候选：需要已确认的英语错题，且词不能已在背诵池里。
                  </Text>
                ) : (
                  <>
                    <Table.ScrollContainer minWidth={360}>
                      <Table striped highlightOnHover>
                        <Table.Thead>
                          <Table.Tr>
                            <Table.Th w={48}>选</Table.Th>
                            <Table.Th>词</Table.Th>
                            <Table.Th>出现错题数</Table.Th>
                          </Table.Tr>
                        </Table.Thead>
                        <Table.Tbody>
                          {candidates.map((candidate) => (
                            <Table.Tr key={candidate.word}>
                              <Table.Td>
                                <Checkbox
                                  aria-label={`选择 ${candidate.word}`}
                                  checked={selectedWords.includes(
                                    candidate.word,
                                  )}
                                  onChange={() =>
                                    setSelectedWords((current) =>
                                      current.includes(candidate.word)
                                        ? current.filter(
                                            (word) => word !== candidate.word,
                                          )
                                        : [...current, candidate.word],
                                    )
                                  }
                                />
                              </Table.Td>
                              <Table.Td>
                                <Text size="sm" ff="monospace">
                                  {candidate.word}
                                </Text>
                              </Table.Td>
                              <Table.Td>{candidate.mistake_count}</Table.Td>
                            </Table.Tr>
                          ))}
                        </Table.Tbody>
                      </Table>
                    </Table.ScrollContainer>
                    <Group align="flex-end" gap="sm" wrap="wrap">
                      <Button
                        size="compact-sm"
                        variant="subtle"
                        onClick={() =>
                          setSelectedWords(candidates.map((row) => row.word))
                        }
                      >
                        全选
                      </Button>
                      <Button
                        size="compact-sm"
                        variant="subtle"
                        onClick={() => setSelectedWords([])}
                      >
                        清空勾选
                      </Button>
                      <TextInput
                        label="单元（可选）"
                        value={candidateUnit}
                        onChange={(event) =>
                          setCandidateUnit(event.currentTarget.value)
                        }
                        placeholder="Unit 1"
                        w={160}
                      />
                      <Button
                        onClick={() => void addSelectedCandidates()}
                        loading={candidateBusy}
                        disabled={selectedWords.length === 0}
                      >
                        入库选中的 {selectedWords.length} 个词
                      </Button>
                    </Group>
                    <Text size="xs" c="dimmed">
                      候选词入库时释义留空（系统不翻译、不生成释义），
                      需要时可在下方条目表里手动补。
                    </Text>
                  </>
                )}
                {candidateReport && (
                  <Alert
                    color={candidateReport.errors.length > 0 ? "yellow" : "teal"}
                    variant="light"
                    title={`抽词入库：成功 ${candidateReport.imported} 条`}
                  >
                    <Stack gap={4}>
                      <Text size="sm">
                        重复 {candidateReport.duplicates.length} 条（已跳过，不覆盖）
                        {candidateReport.duplicates.length > 0
                          ? `：${candidateReport.duplicates
                              .slice(0, 5)
                              .map((row) => row.prompt)
                              .join("、")}${
                              candidateReport.duplicates.length > 5 ? " 等" : ""
                            }`
                          : ""}
                      </Text>
                      {candidateReport.errors.map((issue) => (
                        <Text
                          key={`${issue.line}-${issue.field ?? "none"}`}
                          size="sm"
                        >
                          第 {issue.line} 个词
                          {issue.field ? `（${issue.field}）` : ""}：{issue.reason}
                        </Text>
                      ))}
                      {batchIds.length > 0 && (
                        <Group>
                          <Button
                            size="compact-sm"
                            color="orange"
                            variant="light"
                            onClick={() => void undoBatch()}
                            loading={undoingBatch}
                          >
                            撤销本批（{batchIds.length} 条）
                          </Button>
                        </Group>
                      )}
                    </Stack>
                  </Alert>
                )}

                {items && items.items.length > 0 && (
                  <Table.ScrollContainer minWidth={520}>
                    <Table striped highlightOnHover>
                      <Table.Thead>
                        <Table.Tr>
                          <Table.Th>学科</Table.Th>
                          <Table.Th>条目</Table.Th>
                          <Table.Th>答案</Table.Th>
                          <Table.Th>单元</Table.Th>
                          <Table.Th>状态</Table.Th>
                          <Table.Th />
                        </Table.Tr>
                      </Table.Thead>
                      <Table.Tbody>
                        {items.items.map((item) => (
                          <Table.Tr key={item.id}>
                            <Table.Td>{item.subject}</Table.Td>
                            <Table.Td>
                              <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
                                {item.prompt}
                              </Text>
                            </Table.Td>
                            <Table.Td>{item.answer ?? "—"}</Table.Td>
                            <Table.Td>{item.unit ?? "—"}</Table.Td>
                            <Table.Td>
                              <Badge
                                color={item.status === "active" ? "teal" : "gray"}
                                variant="light"
                              >
                                {item.status === "active" ? "启用" : "已停用"}
                              </Badge>
                            </Table.Td>
                            <Table.Td>
                              <Button
                                size="compact-xs"
                                variant="light"
                                color={item.status === "active" ? "orange" : "teal"}
                                onClick={() => void toggleStatus(item)}
                                loading={busyId === item.id}
                                disabled={busyId !== null}
                              >
                                {item.status === "active" ? "停用" : "启用"}
                              </Button>
                            </Table.Td>
                          </Table.Tr>
                        ))}
                      </Table.Tbody>
                    </Table>
                  </Table.ScrollContainer>
                )}
              </Stack>
            </Card>
          )}

          {unlocked && (
            <Card withBorder>
              <Stack gap="sm">
                <Group justify="space-between" align="center" wrap="wrap">
                  <Text fw={600}>默写卷</Text>
                  <Text size="xs" c="dimmed">
                    生成卷面 → 打印 → 孩子默写 → 家长红笔批改 → 在这里勾选回录
                  </Text>
                </Group>
                <Text size="sm" c="dimmed">
                  勾选 active 条目生成默写卷（词序按下方条目表顺序固化）；
                  卷面只有提示，不含答案。回录的对/错直接进既有记忆阶梯，
                  错词不进错题本。
                </Text>
                {activeItems.length === 0 ? (
                  <Text size="sm" c="dimmed">
                    暂无 active 条目，请先在上方添加或导入词表。
                  </Text>
                ) : (
                  <>
                    <Table.ScrollContainer minWidth={360}>
                      <Table striped highlightOnHover>
                        <Table.Thead>
                          <Table.Tr>
                            <Table.Th w={48}>选</Table.Th>
                            <Table.Th>条目</Table.Th>
                            <Table.Th>学科</Table.Th>
                            <Table.Th>单元</Table.Th>
                          </Table.Tr>
                        </Table.Thead>
                        <Table.Tbody>
                          {activeItems.map((item) => (
                            <Table.Tr key={item.id}>
                              <Table.Td>
                                <Checkbox
                                  aria-label={`选择 ${item.prompt}`}
                                  checked={sheetSelection.includes(item.id)}
                                  onChange={() =>
                                    setSheetSelection((current) =>
                                      current.includes(item.id)
                                        ? current.filter((id) => id !== item.id)
                                        : [...current, item.id],
                                    )
                                  }
                                />
                              </Table.Td>
                              <Table.Td>
                                <Text
                                  size="sm"
                                  style={{ whiteSpace: "pre-wrap" }}
                                >
                                  {item.prompt}
                                </Text>
                              </Table.Td>
                              <Table.Td>{item.subject}</Table.Td>
                              <Table.Td>{item.unit ?? "—"}</Table.Td>
                            </Table.Tr>
                          ))}
                        </Table.Tbody>
                      </Table>
                    </Table.ScrollContainer>
                    <Group gap="sm" wrap="wrap">
                      <Button
                        size="compact-sm"
                        variant="subtle"
                        onClick={() =>
                          setSheetSelection(activeItems.map((item) => item.id))
                        }
                      >
                        全选
                      </Button>
                      <Button
                        size="compact-sm"
                        variant="subtle"
                        onClick={() => setSheetSelection([])}
                      >
                        清空勾选
                      </Button>
                      <Button
                        onClick={() => void generateSheet()}
                        loading={creatingSheet}
                        disabled={sheetSelection.length === 0}
                      >
                        生成默写卷（{sheetSelection.length} 词）
                      </Button>
                    </Group>
                    <Text size="xs" c="dimmed">
                      一张卷只能含同一学科的条目；生成后自动跳转打印页。
                    </Text>
                  </>
                )}

                <Divider my="xs" label="待回录的卷" labelPosition="left" />
                {sheets.length === 0 ? (
                  <Text size="sm" c="dimmed">
                    没有待回录的默写卷。
                  </Text>
                ) : (
                  <Table.ScrollContainer minWidth={480}>
                    <Table striped highlightOnHover>
                      <Table.Thead>
                        <Table.Tr>
                          <Table.Th>卷号</Table.Th>
                          <Table.Th>生成日期</Table.Th>
                          <Table.Th>学科</Table.Th>
                          <Table.Th>单元</Table.Th>
                          <Table.Th>词数</Table.Th>
                          <Table.Th />
                        </Table.Tr>
                      </Table.Thead>
                      <Table.Tbody>
                        {sheets.map((sheet) => (
                          <Table.Tr key={sheet.id}>
                            <Table.Td>#{sheet.id}</Table.Td>
                            <Table.Td>{sheet.created_on}</Table.Td>
                            <Table.Td>{sheet.subject}</Table.Td>
                            <Table.Td>{sheet.unit ?? "—"}</Table.Td>
                            <Table.Td>{sheet.item_ids.length}</Table.Td>
                            <Table.Td>
                              <Group gap={4}>
                                <Button
                                  size="compact-xs"
                                  variant="light"
                                  onClick={() =>
                                    navigate(
                                      `/print/dictation?sheet_id=${sheet.id}`,
                                    )
                                  }
                                >
                                  打印
                                </Button>
                                <Button
                                  size="compact-xs"
                                  onClick={() => void openRecording(sheet.id)}
                                >
                                  回录
                                </Button>
                              </Group>
                            </Table.Td>
                          </Table.Tr>
                        ))}
                      </Table.Tbody>
                    </Table>
                  </Table.ScrollContainer>
                )}

                {recording && (
                  <Card withBorder bg="gray.0">
                    <Stack gap="sm">
                      <Group justify="space-between" align="center" wrap="wrap">
                        <Text fw={600}>
                          回录卷 #{recording.sheet.id}（
                          {recording.sheet.created_on}）
                        </Text>
                        <Button
                          size="compact-xs"
                          variant="subtle"
                          onClick={() => {
                            setRecording(null);
                            setVerdicts({});
                          }}
                        >
                          取消回录
                        </Button>
                      </Group>
                      <Text size="xs" c="dimmed">
                        对照红笔批改结果逐词勾选；已停用条目会自动跳过。
                        同一天已有自评的词沿用既有结果，不重复计数。
                      </Text>
                      {recording.items.map((item, index) => (
                        <Group
                          key={item.item_id}
                          justify="space-between"
                          align="center"
                          wrap="wrap"
                        >
                          <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
                            {index + 1}. {item.prompt}
                            {item.status === "retired" ? "（已停用）" : ""}
                          </Text>
                          {item.status === "active" && (
                            <Group gap={4}>
                              <Button
                                size="compact-xs"
                                color="teal"
                                variant={
                                  verdicts[item.item_id] === "remembered"
                                    ? "filled"
                                    : "light"
                                }
                                onClick={() =>
                                  setVerdicts((current) => ({
                                    ...current,
                                    [item.item_id]: "remembered",
                                  }))
                                }
                              >
                                对
                              </Button>
                              <Button
                                size="compact-xs"
                                color="orange"
                                variant={
                                  verdicts[item.item_id] === "forgot"
                                    ? "filled"
                                    : "light"
                                }
                                onClick={() =>
                                  setVerdicts((current) => ({
                                    ...current,
                                    [item.item_id]: "forgot",
                                  }))
                                }
                              >
                                错
                              </Button>
                            </Group>
                          )}
                        </Group>
                      ))}
                      {recording.missing_item_ids.length > 0 && (
                        <Text size="xs" c="dimmed">
                          {recording.missing_item_ids.length}{" "}
                          个条目已被删除，回录时自动跳过。
                        </Text>
                      )}
                      <Group>
                        <Button
                          onClick={() => void submitRecording()}
                          loading={recordingBusy}
                          disabled={
                            Object.keys(verdicts).length === 0
                          }
                        >
                          批量回录（
                          {Object.keys(verdicts).length} 词）
                        </Button>
                      </Group>
                    </Stack>
                  </Card>
                )}

                {recordReport && (
                  <Alert
                    color="teal"
                    variant="light"
                    title={`卷 #${recordReport.sheet.id} 已回录：${recordReport.results.length} 词入档`}
                    withCloseButton
                    onClose={() => setRecordReport(null)}
                  >
                    <Stack gap={4}>
                      {recordReport.results.map((entry) => (
                        <Text key={entry.item_id} size="sm">
                          「{entry.prompt}」
                          {entry.verdict === "remembered" ? "对" : "错"} →{" "}
                          {entry.graduated
                            ? "已背熟毕业，不再排期"
                            : `第 ${entry.rung + 1} 档 · 下次 ${entry.scheduled_next ?? "—"}`}
                          {entry.created ? "" : "（今日已有自评，沿用既有结果）"}
                        </Text>
                      ))}
                      {recordReport.skipped.map((entry) => (
                        <Text key={entry.item_id} size="sm" c="dimmed">
                          条目 #{entry.item_id}{" "}
                          {entry.reason === "retired"
                            ? "已停用"
                            : "已删除"}
                          ，本次跳过。
                        </Text>
                      ))}
                    </Stack>
                  </Alert>
                )}
              </Stack>
            </Card>
          )}
        </>
      )}
    </Stack>
  );
}
