import {
  Badge,
  Card,
  Group,
  Stack,
  Text,
  TextInput,
  Tooltip,
  UnstyledButton,
} from "@mantine/core";

import type { QuizQuestionView } from "../api/types";
import MathText from "./MathText";

const TYPE_LABELS: Record<string, string> = {
  choice: "选择",
  numeric: "数值",
  short: "短答",
  self: "解答",
};

/** 题图/选项图来自 seed 题库，装载时已过服务端 SVG 白名单净化（app.seed.svg）。 */
export function QuestionFigure({ svg }: { svg: string }) {
  return (
    <div
      style={{ maxWidth: 360, overflowX: "auto", margin: "6px 0" }}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}

export function QuizQualityBadges({
  question,
}: {
  question: QuizQuestionView;
}) {
  const { quality } = question;
  return (
    <Group gap={4} wrap="wrap">
      <Badge variant="light">
        {TYPE_LABELS[question.type] ?? question.type}
      </Badge>
      {question.difficulty && (
        <Badge variant="outline" color="gray">
          {question.difficulty}
        </Badge>
      )}
      {quality.unaudited && (
        <Tooltip label="官方 seed 自述「AI 生成初稿、未教师审核」">
          <Badge color="orange" variant="light">
            未经审核
          </Badge>
        </Tooltip>
      )}
      {!quality.blind_verified && (
        <Tooltip label="该题未经过独立第二遍盲解复核">
          <Badge color="yellow" variant="light">
            未经二遍复核
          </Badge>
        </Tooltip>
      )}
      {quality.verify_status === "unverifiable" && (
        <Tooltip
          label={`未通过自动答案核验${
            quality.verify_reason ? `：${quality.verify_reason}` : ""
          }`}
        >
          <Badge color="gray" variant="light">
            未自动核验
          </Badge>
        </Tooltip>
      )}
    </Group>
  );
}

export default function QuizQuestionCard({
  question,
  answer,
  onAnswer,
  disabled = false,
  index,
}: {
  question: QuizQuestionView;
  answer: string;
  onAnswer: (value: string) => void;
  disabled?: boolean;
  index?: number;
}) {
  const isChoice = question.type === "choice" && question.choices.length > 0;
  return (
    <Card withBorder padding="sm">
      <Stack gap="xs">
        <Group justify="space-between" align="flex-start" wrap="wrap">
          <QuizQualityBadges question={question} />
          {index !== undefined && (
            <Text size="xs" c="dimmed">
              第 {index + 1} 题
            </Text>
          )}
        </Group>
        <MathText text={question.prompt} />
        {question.figure && <QuestionFigure svg={question.figure} />}
        {isChoice ? (
          <Stack gap={6}>
            {question.choices.map((choice) => {
              const selected = answer === choice.key;
              return (
                <UnstyledButton
                  key={choice.key}
                  onClick={() => onAnswer(choice.key)}
                  disabled={disabled}
                  aria-pressed={selected}
                  style={{
                    width: "100%",
                    textAlign: "left",
                    padding: "8px 10px",
                    borderRadius: 6,
                    border: `1px solid ${
                      selected
                        ? "var(--mantine-color-blue-6)"
                        : "var(--mantine-color-gray-3)"
                    }`,
                    background: selected
                      ? "var(--mantine-color-blue-0)"
                      : undefined,
                    cursor: disabled ? "not-allowed" : "pointer",
                  }}
                >
                  <Group gap="xs" align="center" wrap="nowrap">
                    <Badge variant={selected ? "filled" : "outline"} circle>
                      {choice.key}
                    </Badge>
                    <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
                      {choice.text && <MathText text={choice.text} />}
                      {choice.figure && <QuestionFigure svg={choice.figure} />}
                    </Stack>
                  </Group>
                </UnstyledButton>
              );
            })}
          </Stack>
        ) : question.mode === "system" ? (
          <TextInput
            label="作答"
            placeholder={
              question.type === "numeric" ? "填数值即可" : "填写你的答案"
            }
            value={answer}
            maxLength={2000}
            disabled={disabled}
            onChange={(event) => onAnswer(event.currentTarget.value)}
          />
        ) : (
          <Text size="sm" c="dimmed">
            这道题无法在页面内键入，请在纸上完成后再对照卷面自评。
          </Text>
        )}
      </Stack>
    </Card>
  );
}
