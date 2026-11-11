import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Modal,
  Pagination,
  SegmentedControl,
  Select,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { errorMessage } from "../api/client";
import {
  getMistakeOptions,
  listMistakes,
  unvoidMistake,
  type MistakeMasteryState,
} from "../api/endpoints";
import type { ErrorCauseOption, MistakeDetail } from "../api/types";
import CategoryPicker from "../components/CategoryPicker";
import MathText from "../components/MathText";
import { useParentSession } from "../parent/ParentSession";

const PAGE_SIZE = 20;

type MistakeView = "active" | "voided";

const MASTERY_STATE_OPTIONS: { value: MistakeMasteryState; label: string }[] = [
  { value: "pending", label: "待复习" },
  { value: "consolidating", label: "巩固中" },
  { value: "graduated", label: "已掌握" },
];

export default function MistakesPage() {
  const navigate = useNavigate();
  const { unlocked } = useParentSession();
  const [view, setView] = useState<MistakeView>("active");
  const [items, setItems] = useState<MistakeDetail[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [categoryId, setCategoryId] = useState<string | null>(null);
  const [errorCause, setErrorCause] = useState<string | null>(null);
  const [errorCauses, setErrorCauses] = useState<ErrorCauseOption[]>([]);
  const [search, setSearch] = useState("");
  const [masteryState, setMasteryState] = useState<MistakeMasteryState | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [debouncedSearch] = useDebouncedValue(search, 300);

  const [counts, setCounts] = useState<{
    active: number | null;
    voided: number | null;
  }>({ active: null, voided: null });
  const [refreshKey, setRefreshKey] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [restoring, setRestoring] = useState<MistakeDetail | null>(null);
  const [restoreBusy, setRestoreBusy] = useState(false);
  const [restoreError, setRestoreError] = useState<string | null>(null);

  // 回收站只对家长解锁开放；未解锁时既不算 trash 视图，也不渲染入口。
  const isTrash = unlocked && view === "voided";
  const hasFilters = Boolean(
    categoryId || errorCause || debouncedSearch || masteryState,
  );

  // 孩子区永远只看在本：锁定后强制回到 active，避免停留在回收站。
  useEffect(() => {
    if (!unlocked) {
      setView("active");
    }
  }, [unlocked]);

  useEffect(() => {
    let active = true;
    getMistakeOptions()
      .then((response) => {
        if (active) {
          setErrorCauses(response.error_causes);
        }
      })
      .catch(() => {
        // 错因下拉失败不影响列表主流程
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    setOffset(0);
  }, [debouncedSearch, masteryState, view]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    listMistakes({
      status: isTrash ? "voided" : "active",
      categoryId,
      errorCause,
      q: debouncedSearch || null,
      masteryState,
      limit: PAGE_SIZE,
      offset,
    })
      .then((response) => {
        if (!active) {
          return;
        }
        setItems(response.items);
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
  }, [
    categoryId,
    errorCause,
    debouncedSearch,
    masteryState,
    offset,
    isTrash,
    refreshKey,
  ]);

  // 两视图计数（不受筛选影响）：恢复后随 refreshKey 一起刷新。
  useEffect(() => {
    if (!unlocked) {
      return;
    }
    let active = true;
    Promise.all([
      listMistakes({ status: "active", limit: 1 }),
      listMistakes({ status: "voided", limit: 1 }),
    ])
      .then(([activeRes, voidedRes]) => {
        if (active) {
          setCounts({ active: activeRes.total, voided: voidedRes.total });
        }
      })
      .catch(() => {
        // 计数失败不影响列表主流程
      });
    return () => {
      active = false;
    };
  }, [unlocked, refreshKey]);

  async function confirmRestore() {
    if (!restoring || restoreBusy) {
      return;
    }
    setRestoreBusy(true);
    setRestoreError(null);
    try {
      const response = await unvoidMistake(restoring.id, { actor: "parent" });
      setNotice(
        `#${response.id} 已恢复：回到在本列表；未完成排期到期后会重新进入复习队列`,
      );
      setRestoring(null);
      setRefreshKey((value) => value + 1);
    } catch (cause) {
      setRestoreError(errorMessage(cause));
    } finally {
      setRestoreBusy(false);
    }
  }

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center" wrap="wrap">
        <Group gap="sm" align="center">
          <Title order={2}>错题本</Title>
          {unlocked && (
            <SegmentedControl
              size="xs"
              value={view}
              onChange={(value) => setView(value as MistakeView)}
              data={[
                {
                  value: "active",
                  label:
                    counts.active != null ? `在本 (${counts.active})` : "在本",
                },
                {
                  value: "voided",
                  label:
                    counts.voided != null
                      ? `回收站 (${counts.voided})`
                      : "回收站",
                },
              ]}
            />
          )}
        </Group>
        <Group gap="sm">
          <Text size="sm" c="dimmed">
            共 {total} 道
          </Text>
          {!isTrash && (
            <Button
              size="compact-sm"
              variant="light"
              onClick={() => {
                const params = new URLSearchParams();
                if (categoryId) {
                  params.set("category_id", categoryId);
                }
                if (errorCause) {
                  params.set("error_cause", errorCause);
                }
                const query = params.toString();
                navigate(`/print/mistakes${query ? `?${query}` : ""}`);
              }}
            >
              导出打印
            </Button>
          )}
        </Group>
      </Group>

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

      {isTrash && (
        <Alert color="orange" variant="light" title="回收站（家长专属）">
          这里只放已作废的错题：它们已退出在本列表与到期复习队列，但历史版本与复习记录全部保留。
          逐条「恢复」即可撤销作废，回到在本列表。
        </Alert>
      )}

      <Card withBorder>
        <Stack gap="sm">
          <Group align="flex-end" wrap="wrap">
            <div style={{ flex: "1 1 240px", minWidth: 220 }}>
              <TextInput
                label="搜索题干 / 答案"
                placeholder="输入关键词"
                value={search}
                onChange={(event) => setSearch(event.currentTarget.value)}
                maxLength={100}
              />
            </div>
            <div style={{ flex: "1 1 240px", minWidth: 220 }}>
              <CategoryPicker
                value={categoryId}
                onChange={(value) => {
                  setCategoryId(value);
                  setOffset(0);
                }}
                label="按知识点筛选"
                placeholder="搜索知识点"
              />
            </div>
            <div style={{ flex: "1 1 180px", minWidth: 160 }}>
              <Select
                label="按错因筛选"
                data={errorCauses.map((item) => ({
                  value: item.id,
                  label: item.label,
                }))}
                value={errorCause}
                onChange={(value) => {
                  setErrorCause(value);
                  setOffset(0);
                }}
                clearable
                placeholder="全部错因"
              />
            </div>
            <div style={{ flex: "1 1 160px", minWidth: 150 }}>
              <Select
                label="按掌握状态筛选"
                data={MASTERY_STATE_OPTIONS}
                value={masteryState}
                onChange={(value) => {
                  setMasteryState(value as MistakeMasteryState | null);
                  setOffset(0);
                }}
                clearable
                placeholder="全部状态"
              />
            </div>
            {(categoryId || errorCause || search || masteryState) && (
              <Button
                variant="subtle"
                onClick={() => {
                  setCategoryId(null);
                  setErrorCause(null);
                  setSearch("");
                  setMasteryState(null);
                  setOffset(0);
                }}
              >
                清除筛选
              </Button>
            )}
          </Group>
        </Stack>
      </Card>

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

      {!loading && !error && items.length === 0 && (
        <Alert
          color="blue"
          variant="light"
          title={
            isTrash
              ? hasFilters
                ? "没有匹配的已作废错题"
                : "回收站是空的"
              : hasFilters
                ? "没有匹配的错题"
                : "还没有错题"
          }
        >
          {isTrash
            ? hasFilters
              ? "换个关键词或清除筛选试试。"
              : "作废的错题会出现在这里，可逐条恢复到在本列表。"
            : hasFilters
              ? "换个关键词或清除筛选试试。"
              : "先在导入页把外部转录的已批改错题生成草稿，再到核对页确认入本。"}
        </Alert>
      )}

      {items.map((item) => (
        <Card key={item.id} withBorder>
          <Stack gap="xs">
            <Group justify="space-between" align="flex-start" wrap="nowrap">
              <Group gap="xs">
                <Badge variant="light">#{item.id}</Badge>
                {isTrash && (
                  <Badge color="gray" variant="light">
                    已作废
                  </Badge>
                )}
              </Group>
              <Text size="xs" c="dimmed">
                {new Date(item.created_at).toLocaleString()}
              </Text>
            </Group>
            <div style={{ maxHeight: 96, overflow: "hidden" }}>
              <MathText text={item.problem_text || "（无题目文本）"} />
            </div>
            <Group gap="xs" wrap="wrap">
              {item.labels.category_name ? (
                <Badge color="blue" variant="light">
                  {item.labels.category_name}
                </Badge>
              ) : item.suggestion.category_name ? (
                <Badge color="gray" variant="light">
                  建议：{item.suggestion.category_name}
                </Badge>
              ) : (
                <Badge color="yellow" variant="light">
                  未挂知识点
                </Badge>
              )}
              {item.labels.concepts.map((concept) => (
                <Badge key={concept.id} variant="outline">
                  {concept.name}
                </Badge>
              ))}
              {item.labels.error_cause_label && (
                <Badge color="orange" variant="light">
                  {item.labels.error_cause_label}
                </Badge>
              )}
            </Group>
            <Group>
              <Button
                size="compact-sm"
                variant="light"
                onClick={() => navigate(`/mistakes/${item.id}`)}
              >
                {isTrash ? "查看" : "查看 / 补标签"}
              </Button>
              {isTrash && (
                <Button
                  size="compact-sm"
                  variant="light"
                  color="green"
                  onClick={() => {
                    setRestoreError(null);
                    setRestoring(item);
                  }}
                >
                  恢复
                </Button>
              )}
            </Group>
          </Stack>
        </Card>
      ))}

      {total > PAGE_SIZE && (
        <Group justify="center">
          <Pagination
            total={Math.ceil(total / PAGE_SIZE)}
            value={Math.floor(offset / PAGE_SIZE) + 1}
            onChange={(page) => setOffset((page - 1) * PAGE_SIZE)}
          />
        </Group>
      )}

      {restoring && (
        <Modal
          opened
          onClose={() => setRestoring(null)}
          title={`恢复错题 #${restoring.id}`}
          size="md"
        >
          <Stack gap="sm">
            <Alert color="blue" variant="light" title="恢复后果">
              撤销作废：错题回到在本列表；未完成的复习排期到期后会重新进入复习队列。
              历史版本与复习记录全部保留，不会删除任何数据。
            </Alert>
            <div style={{ maxHeight: 120, overflow: "hidden" }}>
              <MathText text={restoring.problem_text || "（无题目文本）"} />
            </div>
            {restoreError && (
              <Alert color="red" variant="light" title="恢复失败">
                {restoreError}
              </Alert>
            )}
            <Group justify="flex-end">
              <Button
                variant="default"
                onClick={() => setRestoring(null)}
                disabled={restoreBusy}
              >
                取消
              </Button>
              <Button
                color="green"
                onClick={() => void confirmRestore()}
                loading={restoreBusy}
              >
                确认恢复
              </Button>
            </Group>
          </Stack>
        </Modal>
      )}
    </Stack>
  );
}
