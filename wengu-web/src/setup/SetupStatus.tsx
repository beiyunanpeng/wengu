import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { getSetupStatus as fetchSetupStatus } from "../api/endpoints";

interface SetupStatusValue {
  completed: boolean | null;
  refresh: () => Promise<void>;
  markCompleted: () => void;
}

const SetupStatusContext = createContext<SetupStatusValue | null>(null);

export function SetupStatusProvider({ children }: { children: ReactNode }) {
  const [completed, setCompleted] = useState<boolean | null>(null);

  const refresh = useCallback(async () => {
    try {
      const status = await fetchSetupStatus();
      setCompleted(status.setup_completed);
    } catch {
      // 后端不可用时不弹横幅，避免把网络故障误报成"未完成"
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const markCompleted = useCallback(() => {
    setCompleted(true);
  }, []);

  const value = useMemo(
    () => ({ completed, refresh, markCompleted }),
    [completed, refresh, markCompleted],
  );

  return (
    <SetupStatusContext.Provider value={value}>
      {children}
    </SetupStatusContext.Provider>
  );
}

export function useSetupStatus(): SetupStatusValue {
  const value = useContext(SetupStatusContext);
  if (!value) {
    throw new Error("useSetupStatus 必须在 SetupStatusProvider 内使用");
  }
  return value;
}
