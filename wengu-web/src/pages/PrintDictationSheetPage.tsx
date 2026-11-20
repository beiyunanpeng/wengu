import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { errorMessage } from "../api/client";
import { getDictationSheet } from "../api/endpoints";
import type { DictationSheetDetail } from "../api/types";
import { toISODate } from "../lib/dates";
import "../print.css";

export default function PrintDictationSheetPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const sheetIdValue = Number(params.get("sheet_id"));
  const sheetId =
    Number.isInteger(sheetIdValue) && sheetIdValue >= 1 ? sheetIdValue : null;

  const [detail, setDetail] = useState<DictationSheetDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (sheetId === null) {
      setLoading(false);
      setError("缺少 sheet_id，请从「英语背诵」页生成默写卷后再打印。");
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    getDictationSheet(sheetId)
      .then((response) => {
        if (active) {
          setDetail(response);
        }
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
  }, [sheetId]);

  const today = toISODate(new Date());
  const printable = Boolean(detail && detail.items.length > 0);

  return (
    <div className="print-shell" data-print-dictation="true">
      <div className="print-toolbar">
        <div className="print-toolbar-title">
          <strong>默写卷</strong>
          <span>
            {detail
              ? `卷号 ${detail.sheet.id} · ${detail.items.length} 词`
              : "看提示写"}
          </span>
        </div>
        <div className="print-actions">
          <button
            type="button"
            className="primary"
            onClick={() => window.print()}
            disabled={loading || !printable}
          >
            打印 / 另存为 PDF
          </button>
          <button type="button" onClick={() => navigate("/recitations")}>
            返回背诵页
          </button>
        </div>
      </div>

      <main className="print-sheet">
        <header className="print-doc-head">
          <div>
            <h1 className="print-doc-title">默写卷</h1>
            <div className="print-meta">
              {detail
                ? `卷号 ${detail.sheet.id} · ${detail.sheet.subject}` +
                  (detail.sheet.unit ? ` · ${detail.sheet.unit}` : "") +
                  ` · 共 ${detail.items.length} 词 · 生成于 ${detail.sheet.created_on}`
                : "看提示，把单词写在横线上"}
            </div>
          </div>
          <div className="print-meta">打印日期 {today}</div>
        </header>

        {loading && <div className="print-empty">正在读取卷面…</div>}
        {error && (
          <div className="print-error" role="alert">
            读取失败：{error}
          </div>
        )}

        {!loading && !error && detail && detail.items.length === 0 && (
          <div className="print-empty">
            本卷条目都已删除，没有可打印的内容；请回背诵页重新生成。
          </div>
        )}

        {!loading &&
          !error &&
          detail?.items.map((item, index) => (
            <article
              className="print-question"
              key={item.item_id}
              data-dictation-item={item.item_id}
            >
              <header className="print-question-head">
                <span>第 {index + 1} 词</span>
                <span>
                  {item.unit ? `${item.unit} · ` : ""}看提示写
                  {item.status === "retired" ? " · 条目已停用" : ""}
                </span>
              </header>
              <div className="print-prompt">{item.prompt}</div>
              <div
                style={{
                  borderBottom: "1px solid #999",
                  height: "2.4em",
                  marginTop: "0.6em",
                }}
              />
            </article>
          ))}

        {detail && detail.missing_item_ids.length > 0 && (
          <p className="print-note">
            有 {detail.missing_item_ids.length} 个条目已被删除，本卷不再列出。
          </p>
        )}

        {printable && (
          <p className="print-note">
            孩子看提示在横线上默写；家长用红笔批改后，回「英语背诵」页按卷勾选回录。
          </p>
        )}
      </main>
    </div>
  );
}