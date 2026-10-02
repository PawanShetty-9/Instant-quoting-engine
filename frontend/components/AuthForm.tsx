"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useId, useState } from "react";
import { ApiError, signIn, signUp, startCheckout, type PlanKey } from "@/lib/api";
import { useSession } from "@/lib/session";

/** Sign-in and sign-up share one form. After sign-up with ?plan=pro the user goes straight to checkout. */
export default function AuthForm({ mode }: { mode: "login" | "signup" }) {
  const id = useId();
  const router = useRouter();
  const session = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [company, setCompany] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const signup = mode === "signup";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = signup ? await signUp(email, password, company) : await signIn(email, password);
      await session.signIn(res.token);
      const plan = new URLSearchParams(window.location.search).get("plan") as PlanKey | null;
      if (plan === "pro" || plan === "business") {
        const { url } = await startCheckout(plan);
        window.location.assign(url);
        return;
      }
      router.push(signup ? "/quote" : "/account");
    } catch (err) {
      const e2 = err as ApiError;
      setError(
        e2.status === 409
          ? "Für diese E-Mail-Adresse gibt es bereits ein Konto."
          : e2.status === 401
            ? "E-Mail oder Passwort ist falsch."
            : e2.status === 422
              ? "Bitte gültige E-Mail und ein Passwort mit mindestens 8 Zeichen angeben."
              : e2.message,
      );
      setBusy(false);
    }
  }

  return (
    <form className="panel auth" onSubmit={submit}>
      <h1>{signup ? "Konto anlegen" : "Anmelden"}</h1>
      <p className="help">{signup ? "Kostenlos, 10 Angebote pro Monat. Upgrade jederzeit." : "Willkommen zurück."}</p>
      <div className="field">
        <label className="label" htmlFor={`${id}-email`}>
          E-Mail
        </label>
        <input
          id={`${id}-email`}
          className="control"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </div>
      <div className="field">
        <label className="label" htmlFor={`${id}-pw`}>
          Passwort <span className="en">· min. 8 Zeichen</span>
        </label>
        <input
          id={`${id}-pw`}
          className="control"
          type="password"
          autoComplete={signup ? "new-password" : "current-password"}
          minLength={8}
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </div>
      {signup && (
        <div className="field">
          <label className="label" htmlFor={`${id}-co`}>
            Firma <span className="en">· optional</span>
          </label>
          <input
            id={`${id}-co`}
            className="control"
            autoComplete="organization"
            value={company}
            onChange={(e) => setCompany(e.target.value)}
          />
        </div>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button className="btn" type="submit" disabled={busy}>
        {busy ? "Bitte warten …" : signup ? "Kostenlos registrieren" : "Anmelden"}
      </button>
      <p className="help">
        {signup ? (
          <>
            Schon registriert? <Link href="/login">Anmelden</Link>
          </>
        ) : (
          <>
            Noch kein Konto? <Link href="/signup">Kostenlos registrieren</Link>
          </>
        )}
      </p>
      {signup && (
        <p className="fineprint">
          Mit der Registrierung akzeptieren Sie unsere <Link href="/impressum#agb">AGB</Link> und die{" "}
          <Link href="/impressum#datenschutz">Datenschutzerklärung</Link>.
        </p>
      )}
    </form>
  );
}
