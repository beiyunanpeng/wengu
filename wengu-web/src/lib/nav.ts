export interface NavItem {
  to: string;
  label: string;
  parentOnly?: boolean;
}

export type NavGroupKey = "student" | "parent";

export interface NavGroup {
  key: NavGroupKey;
  title: string;
  items: NavItem[];
}

export const NAV: NavItem[] = [
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

const GROUP_TITLES: Record<NavGroupKey, string> = {
  student: "孩子组",
  parent: "家长组",
};

export function groupNavItems(items: NavItem[], unlocked: boolean): NavGroup[] {
  const groups: NavGroup[] = [
    {
      key: "student",
      title: GROUP_TITLES.student,
      items: items.filter((item) => !item.parentOnly),
    },
  ];
  const parentItems = items.filter((item) => item.parentOnly);
  if (unlocked && parentItems.length > 0) {
    groups.push({ key: "parent", title: GROUP_TITLES.parent, items: parentItems });
  }
  return groups;
}

export function isNavActive(pathname: string, to: string): boolean {
  return pathname === to || pathname.startsWith(`${to}/`);
}
