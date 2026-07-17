import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

import { ActivityIcon, KeyIcon, ShieldCheckIcon } from "./icons";

const NAV_ITEM = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-[10px] rounded-[8px] px-[10px] py-2 text-[13px] ${
    isActive
      ? "border border-edge bg-white font-semibold text-ink shadow-[0_1px_2px_rgba(0,0,0,0.03)]"
      : "font-medium text-dim hover:bg-[#f2f2f3] hover:text-[#3f3f46]"
  }`;

function Sidebar() {
  return (
    <aside className="flex w-[240px] shrink-0 flex-col border-r border-line bg-subtle px-[14px] py-[18px]">
      <div className="flex items-center gap-[10px] px-[10px] pb-[18px]">
        <span className="flex h-7 w-7 items-center justify-center rounded-[8px] bg-ink text-white">
          <ShieldCheckIcon size={16} />
        </span>
        <span className="text-[15.5px] font-bold tracking-[-0.02em]">
          Sentinel
        </span>
      </div>
      <nav className="flex flex-col gap-[2px]">
        <NavLink to="/monitors" className={NAV_ITEM}>
          <ActivityIcon size={16} />
          Monitors
        </NavLink>
        <NavLink to="/auth-sources" className={NAV_ITEM}>
          <KeyIcon size={16} />
          Auth sources
        </NavLink>
      </nav>
      <div className="mt-auto flex items-center gap-[10px] border-t border-line p-2 pt-[14px]">
        <span className="flex h-[30px] w-[30px] items-center justify-center rounded-[8px] bg-accent text-[12px] font-semibold text-white">
          SN
        </span>
        <span className="min-w-0">
          <span className="block truncate text-[13px] font-semibold">
            Workspace
          </span>
          <span className="block text-[11.5px] text-muted">Self-hosted</span>
        </span>
      </div>
    </aside>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex-1 overflow-y-auto bg-white">{children}</main>
    </div>
  );
}
