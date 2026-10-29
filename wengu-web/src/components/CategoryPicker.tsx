import { Loader, Select } from "@mantine/core";
import { useEffect, useRef, useState } from "react";

import { errorMessage } from "../api/client";
import { searchTopics } from "../api/endpoints";

interface Option {
  value: string;
  label: string;
}

export default function CategoryPicker({
  value,
  onChange,
  label = "知识点分类",
  placeholder = "输入关键词搜索知识点",
  required = false,
  disabled = false,
  initialLabel = null,
}: {
  value: string | null;
  onChange: (value: string | null) => void;
  label?: string;
  placeholder?: string;
  required?: boolean;
  disabled?: boolean;
  initialLabel?: string | null;
}) {
  const [query, setQuery] = useState("");
  const [options, setOptions] = useState<Option[]>([]);
  const [selectedLabel, setSelectedLabel] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const valueRef = useRef(value);
  valueRef.current = value;
  // Mantine 会把选中项 label 回填进搜索框并触发 onSearchChange；记下这次回填，
  // 避免把 label 当用户输入再查一遍（否则 label 格式一变就无限重查）
  const echoedQueryRef = useRef<string | null>(initialLabel ?? null);

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
        searchTopics(query, 20)
          .then((response) => {
            if (!active) {
              return;
            }
            const next = response.items.map((topic) => ({
              value: topic.id,
              label: `${topic.name} · ${topic.subject}`,
            }));
            setOptions(next);
            const current = valueRef.current;
            const hit = current
              ? next.find((option) => option.value === current)
              : undefined;
            if (hit) {
              // 合成兜底项的 label 与真实项保持一致，搜索框里的文本才能稳定
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
      ? [
          {
            value,
            label: selectedLabel ?? initialLabel ?? value,
          },
          ...options,
        ]
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
      required={required}
      disabled={disabled}
      rightSection={loading ? <Loader size="xs" /> : null}
      error={error}
      nothingFoundMessage="没有匹配的知识点"
    />
  );
}
