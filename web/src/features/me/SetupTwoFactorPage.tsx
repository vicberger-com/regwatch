/**
 * `/setup-two-factor` (BL-148; CP-40): where an account that `auth.mfa_required` covers lands
 * until it has an authenticator. The API answers nothing else meanwhile (403
 * mfa-setup-required), like the forced password change.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";

import { meQuery } from "@/lib/auth/session";

import { TwoFactor } from "./TwoFactor";

export function SetupTwoFactorPage() {
  const client = useQueryClient();
  const navigate = useNavigate();
  return (
    <section aria-labelledby="mfa-heading" className="max-w-2xl">
      <h1 id="mfa-heading" className="text-2xl font-semibold">
        Set up two-factor sign-in
      </h1>
      <p className="mt-2">
        Your organisation requires a code from an authenticator app when you
        sign in. Set it up to continue.
      </p>
      <section
        aria-label="Two-factor sign-in"
        className="mt-4 rounded border border-border bg-surface p-4"
      >
        <TwoFactor
          onSaved={() => {
            void client
              .invalidateQueries({ queryKey: meQuery.queryKey })
              .then(() => navigate({ to: "/" }));
          }}
        />
      </section>
    </section>
  );
}
