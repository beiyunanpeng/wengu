import type { DictationSheetDetail, DictationSheetItem } from "../api/types.ts";

export interface DictationPrintRow {
  item_id: number;
  unit: string | null;
  status: DictationSheetItem["status"];
  prompt?: string;
}

// 定案⑥：挂音频的卷面行内不得出现 prompt 字段，否则听写退化成抄写。
export function buildPrintRows(
  detail: DictationSheetDetail,
): DictationPrintRow[] {
  const listening = detail.sheet.audio_ref !== null;
  return detail.items.map((item) =>
    listening
      ? { item_id: item.item_id, unit: item.unit, status: item.status }
      : {
          item_id: item.item_id,
          unit: item.unit,
          status: item.status,
          prompt: item.prompt,
        },
  );
}