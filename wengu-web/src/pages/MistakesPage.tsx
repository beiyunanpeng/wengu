import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Pagination,
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
  type MistakeMasteryState,
} from "../api/endpoints";
import type { ErrorCauseOption, MistakeDetail } from "../api/types";
import CategoryPicker from "../components/CategoryPicker";
import MathText from "../components/MathText";

const PAGE_SIZE = 20;

const MASTERY_STATE_OPTIONS: { value: MistakeMasteryState; label: string }[] = [
  { value: "pending", label: "待复习" },
  { value: "consolidating", label: "巩固中" },
  { value: "graduated", label: "已掌握" },
];

export default function MistakesPage() {
  const navigate = useNavigate();
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
  }, [debouncedSearch, masteryState]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    listMistakes({
      status: "active",
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
  }, [categoryId, errorCause, debouncedSearch, masteryState, offset]);

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center">
        <Title order={2}>错题本</Title>
        <Group gap="sm">
          <Text size="sm" c="dimmed">
            共 {total} 道
          </Text>
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
        </Group>
      </Group>

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
        <Alert color="blue" variant="light" title={categoryId || errorCause || debouncedSearch || masteryState ? "没有匹配的错题" : "还没有错题"}>
          {categoryId || errorCause || debouncedSearch || masteryState
            ? "换个关键词或清除筛选试试。"
            : "先在导入页把外部转录的已批改错题生成草稿，再到核对页确认入本。"}
        </Alert>
      )}

      {items.map((item) => (
        <Card key={item.id} withBorder>
          <Stack gap="xs">
            <Group justify="space-between" align="flex-start" wrap="nowrap">
              <Badge variant="light">#{item.id}</Badge>
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
                查看 / 补标签
              </Button>
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
    </Stack>
  );
}
