import { Link } from "react-router-dom";

import { ArrowLeftIcon } from "../components/icons";

export function AddMonitorPage() {
  return (
    <div className="mx-auto max-w-[740px] px-9 pb-20 pt-[30px]">
      <Link
        to="/monitors"
        className="flex w-fit items-center gap-[6px] text-[13px] font-medium text-dim hover:text-ink"
      >
        <ArrowLeftIcon size={15} />
        Back to monitors
      </Link>
      <h1 className="mt-4 text-2xl font-bold tracking-[-0.02em]">
        Add a monitor
      </h1>
      <p className="mt-2 text-sm text-dim">
        Import an existing request or set one up by hand. Sentinel starts
        watching it immediately.
      </p>
      <div className="mt-6 rounded-[14px] border border-edge px-[18px] py-10 text-center text-[13px] text-dim">
        The cURL / import / manual tabs land in slice S11.3.
      </div>
    </div>
  );
}
