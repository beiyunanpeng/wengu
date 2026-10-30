import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  getSessionStatus,
  lockParent,
  setParentPin,
  unlockParent,
} from "../api/endpoints";

interface ParentSessionValue {
  pinSet: boolean;
  unlocked: boolean;
  loading: boolean;
  refresh: () => Promise<void>;
  unlock: (pin: string) => Promise<void>;
  setPin: (pin: string) => Promise<void>;
  lock: () => Promise<void>;
}

const ParentSessionContext = createContext<ParentSessionValue | null>(null);

export function ParentSessionProvider({ children }: { children: ReactNode }) {
  const [pinSet, setPinSet] = useState(false);
  const [unlocked, setUnlocked] = useState(false);
  const [loading, setLoading] = useState(true);

  const apply = useCallback((nextPinSet: boolean, nextUnlocked: boolean) => {
    setPinSet(nextPinSet);
    setUnlocked(nextUnlocked);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const status = await getSessionStatus();
      apply(status.pin_set, status.parent_unlocked);
    } catch {
      // 后端不可用时按未解锁处理，孩子区不因此报错
      apply(false, false);
    } finally {
      setLoading(false);
    }
  }, [apply]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const unlock = useCallback(
    async (pin: string) => {
      const status = await unlockParent(pin);
      apply(status.pin_set, status.parent_unlocked);
    },
    [apply],
  );

  const setPin = useCallback(
    async (pin: string) => {
      const status = await setParentPin(pin);
      apply(status.pin_set, status.parent_unlocked);
    },
    [apply],
  );

  const lock = useCallback(async () => {
    try {
      await lockParent();
    } catch {
      // 网络失败也先退回本地未解锁态，服务端 cookie 是否清掉由下次刷新确认
    }
    setUnlocked(false);
  }, []);

  const value = useMemo(
    () => ({ pinSet, unlocked, loading, refresh, unlock, setPin, lock }),
    [pinSet, unlocked, loading, refresh, unlock, setPin, lock],
  );

  return (
    <ParentSessionContext.Provider value={value}>
      {children}
    </ParentSessionContext.Provider>
  );
}

export function useParentSession(): ParentSessionValue {
  const value = useContext(ParentSessionContext);
  if (!value) {
    throw new Error("useParentSession 必须在 ParentSessionProvider 内使用");
  }
  return value;
}
