import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { errorMessage } from "../api/client";
import { getMistakeOptions, listMistakes } from "../api/endpoints";
import type { ErrorCauseOption, MistakeDetail } from "../api/types";
import MathText from "../components/MathText";
import { toISODate } from "../lib/dates";
import "../print.css";

const PAGE_SIZE = 200;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

interface MistakeGroup {
  key: string;
  name: string;
  items: MistakeDetail[];
}

function cleanDate(value: string | null): string | null {
  return value && DATE_PATTERN.test(value) ? value : null;
}

function createdDay(item: MistakeDetail): string {
  const date = new Date(item.created_at);
  return Number.isNaN(date.getTime())
    ? item.created_at.slice(0, 10)
    : toISODate(date);
}

function groupMistakes(items: MistakeDetail[]): MistakeGroup[] {
  const groups = new Map<string, MistakeGroup>();
  for (const item of items) {
    const key = item.labels.category_id ?? "__none__";
    const name = item.labels.category_name ?? "未挂知识点";
    let group = groups.get(key);
    if (!group) {
      group = { key, name, items: [] };
      groups.set(key, group);
    }
    group.items.push(item);
  }
  return [...groups.values()].sort((left, right) => {
    if (left.key === "__none__") {
      return 1;
    }
    if (right.key === "__none__") {
      return -1;
    }
    return left.name.localeCompare(right.name, "zh-Hans-CN");
  });
}

export default function PrintMistakesPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const categoryId = params.get("category_id");
  const errorCause = params.get("error_cause");
  const from = cleanDate(params.get("from"));
  const to = cleanDate(params.get("to"));

  const [items, setItems] = useState<MistakeDetail[]>([]);
  const [options, setOptions] = useState<ErrorCauseOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getMistakeOptions()
      .then((response) => {
        if (active) {
          setOptions(response.error_causes);
        }
      })
      .catch(() => {
        // 错因标签只是页眉摘要，失败不影响打印主流程
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);

    async function loadAll() {
      const collected: MistakeDetail[] = [];
      let offset = 0;
      let total = 0;
      do {
        const response = await listMistakes({
          status: "active",
          categoryId,
          errorCause,
          limit: PAGE_SIZE,
          offset,
        });
        collected.push(...response.items);
        total = response.total;
        offset += response.items.length;
        if (response.items.length === 0) {
          break;
        }
      } while (offset < total);
      if (!active) {
        return;
      }
      // 既有错题接口没有日期参数：分页拉全量后在前端按本地日期过滤。
      setItems(
        collected.filter((item) => {
          const day = createdDay(item);
          return (!from || day >= from) && (!to || day <= to);
        }),
      );
    }

    void loadAll()
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
  }, [categoryId, errorCause, from, to]);

  const groups = useMemo(() => groupMistakes(items), [items]);
  const categoryLabel = categoryId
    ? (items.find((item) => item.labels.category_id === categoryId)?.labels
        .category_name ??
      categoryId)
    : "全部知识点";
  const errorLabel =
    options.find((option) => option.id === errorCause)?.label ??
    errorCause ??
    "全部错因";
  const dateLabel =
    from || to ? `${from ?? "最早"} 至 ${to ?? "今天"}` : "全部日期";
  const today = toISODate(new Date());

  return (
    <div className="print-shell">
      <div className="print-toolbar">
        <div className="print-toolbar-title">
          <strong>错题四区块打印</strong>
          <span>
            {categoryLabel} · {errorLabel} · {dateLabel} · {items.length} 道
          </span>
        </div>
        <div className="print-actions">
          <button
            type="button"
            className="primary"
            onClick={() => window.print()}
            disabled={loading || Boolean(error) || items.length === 0}
          >
            打印 / 另存为 PDF
          </button>
          <button type="button" onClick={() => navigate("/mistakes")}>
            返回错题本
          </button>
        </div>
      </div>

      <main className="print-sheet">
        <header className="print-doc-head">
          <div>
            <h1 className="print-doc-title">错题四区块</h1>
            <div className="print-meta">
              知识点：{categoryLabel} · 错因：{errorLabel} · 日期：{dateLabel}
              {groups.length > 0 ? ` · 共 ${groups.length} 个知识点页组` : ""}
            </div>
          </div>
          <div className="print-meta">打印日期 {today}</div>
        </header>

        {loading && <div className="print-empty">正在读取错题…</div>}
        {error && (
          <div className="print-error" role="alert">
            读取失败：{error}
          </div>
        )}

        {!loading && !error && items.length === 0 && (
          <div className="print-empty">
            <div style={{ fontSize: 16, marginBottom: 6 }}>
              当前筛选下没有错题
            </div>
            <div>
              可返回错题本清除筛选，或换个知识点 / 错因 / 日期范围再试。
            </div>
          </div>
        )}

        {!loading &&
          !error &&
          groups.map((group) => (
            <section className="print-group" key={group.key}>
              <h2 className="print-group-title">
                {group.name} <span>（{group.items.length} 道）</span>
              </h2>
              {group.items.map((item) => (
                <article
                  className="print-block"
                  key={item.id}
                  data-mistake-id={item.id}
                >
                  <header className="print-block-head">
                    <span>错题 #{item.id}</span>
                    <span>{createdDay(item)}</span>
                  </header>

                  <section className="print-section">
                    <h3>① 原题</h3>
                    <div className="print-prompt">
                      {item.problem_text ? (
                        <MathText text={item.problem_text} />
                      ) : (
                        "（无题目文本）"
                      )}
                    </div>
                  </section>

                  <section className="print-section">
                    <h3>② 孩子作答</h3>
                    <div className="print-answer wrong">
                      {item.student_answer ? (
                        <MathText text={item.student_answer} />
                      ) : (
                        "（未记录作答）"
                      )}
                    </div>
                  </section>

                  <section className="print-section">
                    <h3>③ 订正正答</h3>
                    <div className="print-answer correct">
                      {item.standard_answer ? (
                        <MathText text={item.standard_answer} />
                      ) : (
                        "（卷面未提供正答）"
                      )}
                    </div>
                  </section>

                  <section className="print-section">
                    <h3>④ 错因批注</h3>
                    <div className="print-tags">
                      <span className="print-tag">
                        错因：
                        {item.labels.error_cause_label ??
                          item.labels.error_cause ??
                          "未确认"}
                      </span>
                      <span className="print-tag">
                        知识点：{item.labels.category_name ?? "未挂知识点"}
                      </span>
                      {item.labels.concepts.map((concept) => (
                        <span className="print-tag" key={concept.id}>
                          {concept.name}
                        </span>
                      ))}
                    </div>
                  </section>
                </article>
              ))}
            </section>
          ))}
      </main>
    </div>
  );
}
