import {
  Alert,
  Button,
  Group,
  Modal,
  PasswordInput,
  Stack,
  Text,
} from "@mantine/core";
import { useState } from "react";

import { errorMessage } from "../api/client";
import { useParentSession } from "../parent/ParentSession";

export default function ParentGate() {
  const { pinSet, unlocked, loading, unlock, setPin, lock } =
    useParentSession();
  const [open, setOpen] = useState(false);
  const [pin, setPinValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function openModal() {
    setPinValue("");
    setError(null);
    setOpen(true);
  }

  async function submit() {
    if (busy) {
      return;
    }
    if (!pin) {
      setError("请输入 PIN");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (pinSet) {
        await unlock(pin);
      } else {
        await setPin(pin);
      }
      setPinValue("");
      setOpen(false);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  async function handleLock() {
    if (busy) {
      return;
    }
    setBusy(true);
    try {
      await lock();
      setOpen(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button
        size="compact-sm"
        variant={unlocked ? "light" : "subtle"}
        color={unlocked ? "green" : undefined}
        onClick={openModal}
        loading={loading}
      >
        {unlocked ? "家长区 · 已解锁" : "家长区"}
      </Button>

      <Modal
        opened={open}
        onClose={() => setOpen(false)}
        title={unlocked ? "家长区" : pinSet ? "解锁家长区" : "设置家长 PIN"}
      >
        {unlocked ? (
          <Stack gap="sm">
            <Text size="sm">
              家长操作已解锁：作废/撤销错题、手动组卷等入口可见。
            </Text>
            <Text size="xs" c="dimmed">
              PIN 只防误入，不是安全边界；公网暴露必须另加鉴权或走
              Tailscale。解锁状态在 12 小时后自动失效。
            </Text>
            <Group justify="flex-end">
              <Button variant="subtle" onClick={() => setOpen(false)}>
                关闭
              </Button>
              <Button
                color="red"
                variant="light"
                onClick={() => void handleLock()}
                loading={busy}
              >
                锁定家长区
              </Button>
            </Group>
          </Stack>
        ) : (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
          >
            <Stack gap="sm">
              <Text size="sm">
                {pinSet
                  ? "输入家长 PIN 后可进行作废/撤销错题、手动组卷等家长操作。"
                  : "首次进入家长区：设置一个 PIN。PIN 只用于区分家长操作，不是安全边界。"}
              </Text>
              <Text size="xs" c="dimmed">
                4–8 位数字，或 6–20 位任意字符。公网暴露必须另加鉴权或走
                Tailscale。
              </Text>
              <PasswordInput
                label={pinSet ? "家长 PIN" : "新 PIN"}
                value={pin}
                onChange={(event) => setPinValue(event.currentTarget.value)}
                autoFocus
                autoComplete="off"
              />
              {error && (
                <Alert color="red" variant="light">
                  {error}
                </Alert>
              )}
              <Group justify="flex-end">
                <Button variant="subtle" onClick={() => setOpen(false)}>
                  取消
                </Button>
                <Button type="submit" loading={busy} disabled={!pin}>
                  {pinSet ? "解锁" : "设置并解锁"}
                </Button>
              </Group>
            </Stack>
          </form>
        )}
      </Modal>
    </>
  );
}
