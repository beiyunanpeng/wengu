import {
  Alert,
  Anchor,
  AppShell,
  Burger,
  Button,
  Container,
  Drawer,
  Group,
  Stack,
  Text,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { useEffect } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";

import ParentGate from "./ParentGate";
import { groupNavItems, isNavActive, NAV, type NavGroup } from "../lib/nav";
import { useParentSession } from "../parent/ParentSession";
import { shouldShowSeedBanner } from "../setup/seedBanner";
import { useSetupStatus } from "../setup/SetupStatus";

const NAVBAR_WIDTH = 220;
const NAVBAR_BREAKPOINT = "sm";

function NavSections({
  groups,
  pathname,
  onNavigate,
}: {
  groups: NavGroup[];
  pathname: string;
  onNavigate: () => void;
}) {
  return (
    <Stack gap="lg">
      {groups.map((group) => (
        <Stack gap={4} key={group.key}>
          <Text size="xs" fw={600} c="dimmed" px="xs">
            {group.title}
          </Text>
          {group.items.map((item) => {
            const active = isNavActive(pathname, item.to);
            return (
              <Button
                key={item.to}
                component={Link}
                to={item.to}
                size="compact-md"
                justify="flex-start"
                variant={active ? "filled" : "subtle"}
                aria-current={active ? "page" : undefined}
                onClick={onNavigate}
              >
                {item.label}
              </Button>
            );
          })}
        </Stack>
      ))}
    </Stack>
  );
}

export default function AppLayout() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const { unlocked } = useParentSession();
  const { completed, seedLoaded } = useSetupStatus();
  const [navOpened, { toggle, close }] = useDisclosure(false);
  const groups = groupNavItems(NAV, unlocked);

  useEffect(() => {
    close();
  }, [pathname, close]);

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{
        width: NAVBAR_WIDTH,
        breakpoint: NAVBAR_BREAKPOINT,
        collapsed: { mobile: true },
      }}
      padding={0}
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="xs" wrap="nowrap">
            <Burger
              opened={navOpened}
              onClick={toggle}
              hiddenFrom={NAVBAR_BREAKPOINT}
              size="sm"
              aria-label="打开导航菜单"
            />
            <Text
              fw={700}
              size="lg"
              style={{ cursor: "pointer", whiteSpace: "nowrap" }}
              onClick={() => navigate("/import")}
            >
              wengu · 温故
            </Text>
          </Group>
          <ParentGate />
        </Group>
      </AppShell.Header>
      <AppShell.Navbar p="md" style={{ overflowY: "auto" }}>
        <NavSections groups={groups} pathname={pathname} onNavigate={close} />
      </AppShell.Navbar>
      <Drawer
        opened={navOpened}
        onClose={close}
        position="left"
        size={NAVBAR_WIDTH}
        title="导航"
        padding="md"
      >
        <NavSections groups={groups} pathname={pathname} onNavigate={close} />
      </Drawer>
      <AppShell.Main>
        {shouldShowSeedBanner(seedLoaded) && (
          <Alert
            color="red"
            variant="light"
            radius={0}
            py="xs"
            aria-label="学科 seed 未装载警告"
          >
            <Text size="sm">学科 seed 未装载：检查 seeds/data/*.json</Text>
          </Alert>
        )}
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
