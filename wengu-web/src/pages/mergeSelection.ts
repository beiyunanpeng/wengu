export interface MergeSelection {
  sourceId: string | null;
  targetId: string | null;
}

export function initialMergeSelection(
  _conceptIds: readonly number[],
): MergeSelection {
  // 归并方向由家长显式选择：即使当前错题只有一个 concept，也不把它预选为源。
  return { sourceId: null, targetId: null };
}

export function isMergeSelectionReady(selection: MergeSelection): boolean {
  return Boolean(
    selection.sourceId &&
      selection.targetId &&
      selection.sourceId !== selection.targetId,
  );
}
