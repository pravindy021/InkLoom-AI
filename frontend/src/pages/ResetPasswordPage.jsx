import { useState } from "react";
import { Link } from "react-router-dom";
import { KeyRound } from "lucide-react";
import { api, errorMessage } from "../services/api";
import { ErrorMessage } from "../components/common/UI";

function takeTokenFromFragment() {
  const token = new URLSearchParams(window.location.hash.slice(1)).get("token") || "";
  if (token) window.history.replaceState(null, "", window.location.pathname);
  return token;
}

export default function ResetPasswordPage() {
  const [token] = useState(takeTokenFromFragment);
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [complete, setComplete] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    setError("");
    if (password !== confirmation) {
      setError("The new passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await api.resetPassword(token, password);
      setComplete(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return <main className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-12">
    <section className="card w-full max-w-md p-6 sm:p-8">
      <div className="mb-5 flex h-11 w-11 items-center justify-center rounded-xl bg-ink-50 text-ink-700"><KeyRound size={21} /></div>
      <h1 className="text-xl font-bold text-ink-900">Set a new password</h1>
      {complete ? <div className="mt-4"><p className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm leading-6 text-emerald-900" role="status">Your password has been changed and existing sessions revoked. Sign in with the new password.</p><Link className="btn-primary mt-5 w-full justify-center" to="/login">Return to sign in</Link></div> : <>
        <p className="mt-1 text-sm leading-6 text-slate-500">Choose a password with at least 12 characters. This recovery link can only be used once.</p>
        {!token && <p className="mt-5 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">This link is missing or invalid. Request a new recovery email.</p>}
        {error && <div className="mt-5"><ErrorMessage>{error}</ErrorMessage></div>}
        <form onSubmit={submit} className="mt-6 space-y-4">
          <div><label className="mb-1.5 block text-sm font-medium text-slate-700" htmlFor="new-password">New password</label><input id="new-password" type="password" autoComplete="new-password" minLength={12} required maxLength={128} value={password} onChange={(event) => setPassword(event.target.value)} className="field" /></div>
          <div><label className="mb-1.5 block text-sm font-medium text-slate-700" htmlFor="confirm-password">Confirm new password</label><input id="confirm-password" type="password" autoComplete="new-password" minLength={12} required maxLength={128} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} className="field" /></div>
          <button className="btn-primary w-full justify-center" type="submit" disabled={busy || !token}>{busy ? "Saving…" : "Reset password"}</button>
        </form>
      </>}
      <Link className="mt-5 inline-block text-sm text-slate-500 underline hover:text-ink-700" to="/forgot-password">Request another link</Link>
    </section>
  </main>;
}
