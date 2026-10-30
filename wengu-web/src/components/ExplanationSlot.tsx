import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Stack,
  Text,
} from "@mantine/core";
import { useState } from "react";

import { errorMessage } from "../api/client";
import { getMistake } from "../api/endpoints";
import type { MistakeDetail } from "../api/types";
import MathText from "./MathText";

/**
 * v2.5 讲解位：默认关。批改/引导/解析都在系统外完成，这里只回放卷面信息
 * （原题 / 划掉的错答 / 订正后的正答）+ 错因与知识点，不调用任何模型。
 */
export default function ExplanationSlot({ mistakeId }: { mistakeId: number }) {
  const [opened, setOpened] = useState(false);
  const [detail, setDetail] = useState<MistakeDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggle() {
    const next = !opened;
    setOpened(next);
    if (!next || detail !== null || loading) {
      return;
    }
    setLoading(true);
    try {
      setDetail(await getMistake(mistakeId));
      setError(null);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setLoading(false);
    }
  }

  return (
    <Stack gap={6}>
      <Group>
        <Button size="compact-sm" variant="subtle" onClick={() => void toggle()}>
          {opened ? "收起讲解位" : "讲解位（默认关）· 看卷面订正"}
        </Button>
      </Group>
      {opened && (
        <Card withBorder padding="sm">
          {loading && <Loader size="sm" />}
          {error && (
            <Alert color="red" variant="light">
              {error}
            </Alert>
          )}
          {detail && (
            <Stack gap="xs">
              <Group gap={6} wrap="wrap">
                {detail.labels.category_name && (
                  <Badge color="blue" variant="light">
                    {detail.labels.category_name}
                  </Badge>
                )}
                {detail.labels.concepts.map((concept) => (
                  <Badge key={concept.id} variant="outline">
                    {concept.name}
                  </Badge>
                ))}
                {detail.labels.error_cause_label && (
                  <Badge color="orange" variant="light">
                    {detail.labels.error_cause_label}
                  </Badge>
                )}
              </Group>
              <div>
                <Text size="xs" c="dimmed" fw={600}>
                  原题
                </Text>
                <MathText text={detail.problem_text || "（题目文本缺失）"} />
              </div>
              <div>
                <Text size="xs" c="dimmed" fw={600}>
                  划掉的错答
                </Text>
                <MathText text={detail.student_answer || "（空）"} />
              </div>
              <div>
                <Text size="xs" c="dimmed" fw={600}>
                  卷面订正的正答
                </Text>
                <MathText text={detail.standard_answer || "（未提供）"} />
              </div>
              <Text size="xs" c="dimmed">
                批改与讲解在系统外完成（卷面红笔 + 拿不准找豆包/家长）。
                系统不生成讲解、不调用模型，这里只回放卷面订正。
              </Text>
            </Stack>
          )}
        </Card>
      )}
    </Stack>
  );
}
