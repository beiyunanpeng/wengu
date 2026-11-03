import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  NumberInput,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { errorMessage } from "../api/client";
import { getAppConfig, getSeedSummary, putAppConfig } from "../api/endpoints";
import type { AppConfig, AppConfigValues, SeedSummary } from "../api/types";
import ParentGate from "../components/ParentGate";
import { useParentSession } from "../parent/ParentSession";
import { useSetupStatus } from "../setup/SetupStatus";

const SUBJECTS = [
  { key: "数学", label: "数学" },
  { key: "英语", label: "英语" },
  { key: "物理", label: "物理" },
  { key: "语文", label: "语文" },
  { key: "化学", label: "化学" },
] as const;

type Limits = Pick<
  AppConfigValues,
  "daily_review_limit" | "daily_recitation_limit" | "exam_day_limit_factor"
>;

const DEFAULT_LIMITS: Limits = {
  daily_review_limit: 10,
  daily_recitation_limit: 5,
  exam_day_limit_factor: 1.5,
};

function toLimits(values: AppConfigValues): Limits {
  return {
    daily_review_limit: values.daily_review_limit,
    daily_recitation_limit: values.daily_recitation_limit,
    exam_day_limit_factor: values.exam_day_limit_factor,
  };
}

export default function SetupPage() {
  const { unlocked } = useParentSession();
  const { markCompleted } = useSetupStatus();
  const [summary, setSummary] = useState<SeedSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [limits, setLimits] = useState<Limits>(DEFAULT_LIMITS);
  const [configLoading, setConfigLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getSeedSummary()
      .then((next) => {
        if (active) {
          setSummary(next);
        }
      })
      .catch((cause) => {
        if (active) {
          setSummaryError(errorMessage(cause));
        }
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!unlocked) {
      setConfig(null);
      return;
    }
    let active = true;
    setConfigLoading(true);
    setError(null);
    getAppConfig()
      .then((next) => {
        if (!active) {
          return;
        }
        setConfig(next);
        setLimits(toLimits(next.values));
        if (next.values.setup_completed) {
          markCompleted();
        }
      })
      .catch((cause) => {
        if (active) {
          setError(errorMessage(cause));
        }
      })
      .finally(() => {
        if (active) {
          setConfigLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [unlocked, markCompleted]);

  function setLimit(key: keyof Limits, value: string | number) {
    const parsed = typeof value === "number" ? value : Number(value);
    setLimits((prev) => ({
      ...prev,
      [key]: Number.isFinite(parsed) ? parsed : 0,
    }));
  }

  async function saveLimits() {
    if (busy) {
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const next = await putAppConfig(limits);
      setConfig(next);
      setLimits(toLimits(next.values));
      setNotice("已生效，无需重启。");
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  async function finish(skipped: boolean) {
    if (busy) {
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const next = await putAppConfig({ setup_completed: true });
      setConfig(next);
      markCompleted();
      setNotice(
        skipped
          ? "已跳过引导；顶部提示已隐藏，可随时回到本页调整。"
          : "设置完成；顶部提示已隐藏。",
      );
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Stack gap="lg">
      <div>
        <Title order={2}>首次运行设置向导</Title>
        <Text size="sm" c="dimmed">
          只做三件有作用的事：看看学科 seed 覆盖、设置运行上限、标记完成。
          不采集孩子个人信息，也不强制跳转。
        </Text>
      </div>

      {notice && (
        <Alert color="green" variant="light">
          {notice}
        </Alert>
      )}
      {error && (
        <Alert color="red" variant="light">
          {error}
        </Alert>
      )}

      <Card withBorder>
        <Stack gap="sm">
          <Title order={3}>① 学科 seed 覆盖</Title>
          <Text size="sm" c="dimmed">
            初中 7–9 全量装载；家里一个孩子、全部学科，不按年级过滤。
          </Text>
          {summaryError && (
            <Alert color="red" variant="light">
              {summaryError}
            </Alert>
          )}
          {!summary && !summaryError && <Loader size="sm" />}
          {summary && (
            <>
              <Text size="sm">
                共 {summary.topics_total} 个知识点、{summary.edges_total} 条先修边。
              </Text>
              <Stack gap="xs">
                {SUBJECTS.map((subject) => {
                  // group_by 不返回零主题学科，缺席必须按 0 展示。
                  const topics = summary.subjects[subject.key]?.topics ?? 0;
                  return (
                    <Group
                      key={subject.key}
                      justify="space-between"
                      gap="xs"
                      wrap="wrap"
                    >
                      <Group gap="xs">
                        <Text fw={500}>{subject.label}</Text>
                        <Badge
                          color={topics > 0 ? "green" : "orange"}
                          variant="light"
                        >
                          {topics} 个知识点
                        </Badge>
                      </Group>
                      {topics === 0 && (
                        <Anchor component={Link} to="/local-seed" size="sm">
                          去「学科 seed」建章级知识点
                        </Anchor>
                      )}
                    </Group>
                  );
                })}
              </Stack>
            </>
          )}
        </Stack>
      </Card>

      <Card withBorder>
        <Stack gap="sm">
          <Title order={3}>② 复习与背诵上限</Title>
          {!unlocked ? (
            <Stack gap="sm">
              <Text size="sm" c="dimmed">
                写入配置需要家长解锁。
              </Text>
              <Group>
                <ParentGate />
              </Group>
            </Stack>
          ) : configLoading ? (
            <Loader size="sm" />
          ) : (
            <>
              {config?.legacy && config.hint && (
                <Alert color="yellow" variant="light">
                  {config.hint}
                </Alert>
              )}
              <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm">
                <NumberInput
                  label="每日复习上限"
                  min={1}
                  max={200}
                  value={limits.daily_review_limit}
                  onChange={(value) => setLimit("daily_review_limit", value)}
                />
                <NumberInput
                  label="每日背诵上限"
                  min={1}
                  max={20}
                  value={limits.daily_recitation_limit}
                  onChange={(value) =>
                    setLimit("daily_recitation_limit", value)
                  }
                />
                <NumberInput
                  label="考试日放大系数"
                  min={1}
                  max={3}
                  step={0.1}
                  decimalScale={2}
                  value={limits.exam_day_limit_factor}
                  onChange={(value) =>
                    setLimit("exam_day_limit_factor", value)
                  }
                />
              </SimpleGrid>
              <Group justify="flex-end">
                <Button onClick={() => void saveLimits()} loading={busy}>
                  保存上限
                </Button>
              </Group>
            </>
          )}
        </Stack>
      </Card>

      <Card withBorder>
        <Stack gap="sm">
          <Title order={3}>③ 完成 / 跳过</Title>
          <Text size="sm" c="dimmed">
            完成和跳过都只写同一个“不再提示”标记，不会采集姓名、生日、年级或照片。
          </Text>
          {!unlocked ? (
            <Text size="sm" c="dimmed">
              解锁家长区后可标记完成。
            </Text>
          ) : (
            <Group wrap="wrap">
              <Button onClick={() => void finish(false)} loading={busy}>
                完成设置
              </Button>
              <Button
                variant="light"
                onClick={() => void finish(true)}
                loading={busy}
              >
                跳过
              </Button>
              {config?.values.setup_completed && (
                <Badge color="green" variant="light">
                  已完成
                </Badge>
              )}
            </Group>
          )}
        </Stack>
      </Card>
    </Stack>
  );
}
