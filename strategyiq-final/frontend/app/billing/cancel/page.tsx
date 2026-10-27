import Link from "next/link";
import { SEC_DISCLAIMER } from "@/lib/constants";

export default function BillingCancelPage() {
  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="panel w-full max-w-md space-y-4 text-center">
        <h1 className="text-terminal-accent text-xl font-bold">Checkout canceled</h1>
        <p className="text-sm text-terminal-muted">
          No charge was made. You can restart checkout whenever you are ready.
        </p>
        <div className="flex gap-3 justify-center text-sm">
          <Link
            href="/billing"
            className="bg-terminal-accent text-terminal-bg px-4 py-2 rounded font-semibold"
          >
            Back to billing
          </Link>
          <Link href="/" className="border border-terminal-border px-4 py-2 rounded text-terminal-muted">
            Terminal
          </Link>
        </div>
        <p className="text-xs text-terminal-muted">{SEC_DISCLAIMER}</p>
      </div>
    </div>
  );
}
