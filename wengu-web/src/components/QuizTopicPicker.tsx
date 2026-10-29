import { Loader, Select } from "@mantine/core";
import { useEffect, useRef, useState } from "react";

import { errorMessage } from "../api/client";
import { listQuizTopics } from "../api/endpoints";

interface Option {
  value: string;
  label: string;
}

/** 只列题库里有题的知识点（组卷按 topic_id 检索，没题的知识点抽不出卷）。 */
export default function QuizTopicPicker({
  value,
  onChange,
  label = "知识点",
  placeholder = "输入关键词搜索有题的知识点",
  disabled = false,
}: {
  value: string | null;
  onChange: (value: string | null) => void;
  label?: string;
  placeholder?: string;
  disabled?: boolean;
}) {
  const [query, setQuery] = useState("");
  const [options, setOptions] = useState<Option[]>([]);
  const [selectedLabel, setSelectedLabel] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const valueRef = useRef(value);
  valueRef.current = value;
  const echoedQueryRef = useRef<string | null>(null);

  function handleSearchChange(next: string) {
    if (next && next === echoedQueryRef.current) {
      echoedQueryRef.current = null;
      return;
    }
    setQuery(next);
  }

  useEffect(() => {
    let active = true;
    const timer = setTimeout(
      () => {
        setLoading(true);
        listQuizTopics({ q: query, limit: 30 })
          .then((response) => {
            if (!active) {
              return;
            }
            const next = response.items.map((topic) => ({
              value: topic.topic_id,
              label: `${topic.name} · ${topic.subject}（可答 ${topic.answerable}/${topic.total}）`,
            }));
            setOptions(next);
            const current = valueRef.current;
            const hit = current
              ? next.find((option) => option.value === current)
              : undefined;
            if (hit) {
              setSelectedLabel(hit.label);
              echoedQueryRef.current = hit.label;
            }
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
      },
      query ? 300 : 0,
    );
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [query]);

  const data =
    value && !options.some((option) => option.value === value)
      ? [{ value, label: selectedLabel ?? value }, ...options]
      : options;

  return (
    <Select
      label={label}
      placeholder={placeholder}
      data={data}
      value={value}
      onChange={(next) => {
        const label =
          options.find((option) => option.value === next)?.label ?? null;
        setSelectedLabel(label);
        echoedQueryRef.current = label;
        setQuery("");
        onChange(next);
      }}
      onSearchChange={handleSearchChange}
      searchable
      clearable
      disabled={disabled}
      rightSection={loading ? <Loader size="xs" /> : null}
      error={error}
      nothingFoundMessage="没有匹配的知识点（题库无题的知识点不会出现在这里）"
    />
  );
}
