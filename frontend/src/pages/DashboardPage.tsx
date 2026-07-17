import { Link } from "react-router-dom";

import { PlusIcon } from "../components/icons";

export function DashboardPage() {
  return (
    <div className="mx-auto max-w-[1080px] px-9 pb-16 pt-[30px]">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-[-0.02em]">Monitors</h1>
          <div className="mt-2 flex items-center gap-2 text-[13px] text-dim">
            <span className="snt-pulse h-[7px] w-[7px] rounded-full bg-up" />
            Live · checking every 30s
          </div>
        </div>
        <Link
          to="/monitors/new"
          className="flex items-center gap-[6px] rounded-[9px] bg-ink px-[14px] py-[9px] text-[13px] font-semibold text-white shadow-[0_1px_2px_rgba(0,0,0,0.12)] hover:bg-black"
        >
          <PlusIcon size={15} />
          Add monitor
        </Link>
      </div>
      <div className="mt-6 rounded-[14px] border border-edge px-[18px] py-10 text-center text-[13px] text-dim">
        The monitor grid lands in the next slice (S11.2).
      </div>
    </div>
  );
}
