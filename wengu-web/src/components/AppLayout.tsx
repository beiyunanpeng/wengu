import {
  Alert,
  Anchor,
  AppShell,
  Button,
  Container,
  Group,
  Text,
} from "@mantine/core";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";

import ParentGate from "./ParentGate";
import { useParentSession } from "../parent/ParentSession";
import { useSetupStatus } from "../setup/SetupStatus";

const NAV: { to: string; label: string; parentOnly?: boolean }[] = [
  { to: "/dashboard", label: "看板" },
  { to: "/import", label: "导入" },
  { to: "/intake", label: "核对" },
  { to: "/mistakes", label: "错题本" },
  { to: "/review", label: "复习考核" },
  { to: "/recitations", label: "英语背诵" },
  { to: "/schedule", label: "课表/日历" },
  { to: "/records", label: "练习记录" },
  { to: "/bank", label: "题库审核", parentOnly: true },
  { to: "/local-seed", label: "学科 seed", parentOnly: true },
  { to: "/backup", label: "备份", parentOnly: true },
];

export default function AppLayout() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const { unlocked } = useParentSession();
  const { completed } = useSetupStatus();
  const navItems = NAV.filter((item) => !item.parentOnly || unlocked);

  return (
    <AppShell header={{ height: 56 }} padding={0}>
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Text
            fw={700}
            size="lg"
            style={{ cursor: "pointer", whiteSpace: "nowrap" }}
            onClick={() => navigate("/import")}
          >
            wengu · 温故
          </Text>
          <Group gap={4} wrap="nowrap">
            {navItems.map((item) => {
              const active =
                pathname === item.to || pathname.startsWith(`${item.to}/`);
              return (
                <Button
                  key={item.to}
                  size="compact-sm"
                  variant={active ? "filled" : "subtle"}
                  onClick={() => navigate(item.to)}
                >
                  {item.label}
                </Button>
              );
            })}
            <ParentGate />
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Main>
        {completed === false && (
          <Alert
            color="blue"
            variant="light"
            radius={0}
            py="xs"
            aria-label="首次运行设置提示"
          >
            <Group gap="xs" justify="space-between" wrap="wrap">
              <Text size="sm">
                首次使用：花 1 分钟看看学科 seed 覆盖、设定每日复习与背诵上限。
              </Text>
              <Anchor component={Link} to="/setup" size="sm" fw={600}>
                进入设置向导
              </Anchor>
            </Group>
          </Alert>
        )}
        <Container size="lg" py="md">
          <Outlet />
        </Container>
      </AppShell.Main>
    </AppShell>
  );
}
