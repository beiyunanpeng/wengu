import { Loader, Select } from "@mantine/core";
import { useEffect, useState } from "react";

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
            setOptions(
              response.items.map((topic) => ({
                value: topic.id,
                label: `${topic.name} · ${topic.subject}`,
              })),
            );
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
        setSelectedLabel(
          options.find((option) => option.value === next)?.label ?? null,
        );
        onChange(next);
      }}
      onSearchChange={setQuery}
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
