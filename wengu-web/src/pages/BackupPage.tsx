import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Code,
  Group,
  Loader,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { useEffect, useState } from "react";

import { errorMessage } from "../api/client";
import { backupDownloadUrl, exportBackup, listBackups } from "../api/endpoints";
import type {
  BackupExportResponse,
  BackupListResponse,
} from "../api/types";
import { useParentSession } from "../parent/ParentSession";

function formatBytes(size: number): string {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / (1024 * 1024)).toFixed(2)} MB`;
}

function formatTime(value: string): string {
  return value.replace("T", " ").replace("Z", " UTC");
}

export default function BackupPage() {
  const { unlocked, loading: sessionLoading } = useParentSession();
  const [data, setData] = useState<BackupListResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [exported, setExported] = useState<BackupExportResponse | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    if (!unlocked) {
      setData(null);
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    listBackups()
      .then((next) => {
        if (active) {
          setData(next);
        }
      })
      .catch((cause) => {
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
  }, [unlocked, refreshKey]);

  async function handleExport() {
    if (busy) {
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await exportBackup();
      setExported(result);
      setRefreshKey((value) => value + 1);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  if (!sessionLoading && !unlocked) {
    return (
      <Stack gap="md">
        <Title order={2}>备份</Title>
        <Alert color="orange" variant="light" title="家长专属">
          备份包含全部错题与练习数据，只对家长开放。请点右上角「家长区」解锁后再进入；
          未解锁时接口返回 403，孩子区不显示本页入口。
        </Alert>
      </Stack>
    );
  }

  if (sessionLoading || (unlocked && loading && !data)) {
    return (
      <Group justify="center" py="xl">
        <Loader />
      </Group>
    );
  }

  const keep = data?.keep ?? 10;

  return (
    <Stack gap="md">
      <Title order={2}>备份</Title>

      <Alert color="blue" variant="light" title="备份 = 一致性快照">
        导出用 SQLite `VACUUM INTO` 生成快照，再打包 `wengu.db`、`uploads/`、
        `seeds_local/`、`inbox/` 与 `manifest.json`（含 sha256 与计数）。全程只读业务库；
        服务端只保留最近 {keep} 份。备份含全部错题，请勿上传到任何外部服务。
      </Alert>

      <Alert color="orange" variant="light" title="恢复请按文档停机操作">
        本系统不做运行中热替换数据库。恢复 = 停服务后整库替换，按仓库
        `docs/deploy/backup-restore.md` 使用 `scripts/restore.ps1`；本页只负责导出与下载。
      </Alert>

      {error && (
        <Alert color="red" variant="light" title="操作失败">
          {error}
        </Alert>
      )}

      <Card withBorder>
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <div>
            <Text fw={600}>导出当前数据</Text>
            <Text size="sm" c="dimmed">
              生成后落在服务端 `data/backups/`，可在下方列表下载。
            </Text>
          </div>
          <Button onClick={() => void handleExport()} loading={busy}>
            立即导出
          </Button>
        </Group>

        {exported && (
          <Alert
            mt="md"
            color="teal"
            variant="light"
            title={`已生成 ${exported.filename}`}
          >
            <Stack gap={4}>
              <Text size="sm">
                大小 {formatBytes(exported.size_bytes)} · 错题{" "}
                {exported.manifest.counts.mistakes ?? 0} 道 · 事件{" "}
                {exported.manifest.counts.learning_events ?? 0} 条 · 文件{" "}
                {exported.manifest.file_count} 个
              </Text>
              <Text size="xs">
                sha256 <Code>{exported.sha256}</Code>
              </Text>
              <Group>
                <Anchor
                  href={backupDownloadUrl(exported.filename)}
                  download={exported.filename}
                >
                  下载这份备份
                </Anchor>
              </Group>
            </Stack>
          </Alert>
        )}
      </Card>

      <Card withBorder>
        <Group justify="space-between" mb="sm">
          <Group gap="xs">
            <Text fw={600}>现有备份</Text>
            <Badge variant="light">{data?.total ?? 0} 份</Badge>
          </Group>
          <Button
            size="compact-sm"
            variant="subtle"
            onClick={() => setRefreshKey((value) => value + 1)}
            loading={loading}
          >
            刷新
          </Button>
        </Group>

        {notice && (
          <Alert color="blue" variant="light" mb="sm">
            {notice}
          </Alert>
        )}

        {data && data.items.length > 0 ? (
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>文件名</Table.Th>
                <Table.Th>时间</Table.Th>
                <Table.Th>大小</Table.Th>
                <Table.Th>sha256</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {data.items.map((item) => (
                <Table.Tr key={item.filename}>
                  <Table.Td>
                    <Text size="sm">{item.filename}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{formatTime(item.created_at)}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{formatBytes(item.size_bytes)}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Code>{item.sha256.slice(0, 12)}…</Code>
                  </Table.Td>
                  <Table.Td>
                    <Anchor
                      href={backupDownloadUrl(item.filename)}
                      download={item.filename}
                      size="sm"
                      onClick={() => setNotice(`开始下载 ${item.filename}`)}
                    >
                      下载
                    </Anchor>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        ) : (
          <Text size="sm" c="dimmed">
            暂无备份。点上方「立即导出」生成第一份。
          </Text>
        )}
      </Card>
    </Stack>
  );
}
