import { AppShell, Button, Container, Group, Text } from "@mantine/core";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import ParentGate from "./ParentGate";

const NAV = [
  { to: "/dashboard", label: "看板" },
  { to: "/import", label: "导入" },
  { to: "/intake", label: "核对" },
  { to: "/mistakes", label: "错题本" },
  { to: "/review", label: "复习考核" },
  { to: "/schedule", label: "课表/日历" },
  { to: "/records", label: "练习记录" },
];

export default function AppLayout() {
  const { pathname } = useLocation();
  const navigate = useNavigate();

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
            {NAV.map((item) => {
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
        <Container size="lg" py="md">
          <Outlet />
        </Container>
      </AppShell.Main>
    </AppShell>
  );
}
