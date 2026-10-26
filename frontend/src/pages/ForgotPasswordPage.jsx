import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Mail } from "lucide-react";
import { api, errorMessage } from "../services/api";
import { ErrorMessage } from "../components/common/UI";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      await api.requestPasswordRecovery(email.trim());
      setSent(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return <main className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-12">
    <section className="card w-full max-w-md p-6 sm:p-8">
      <div className="mb-5 flex h-11 w-11 items-center justify-center rounded-xl bg-ink-50 text-ink-700"><Mail size={21} /></div>
      <h1 className="text-xl font-bold text-ink-900">Recover your password</h1>
      <p className="mt-1 text-sm leading-6 text-slate-500">Enter your workspace email. If an active account matches, recovery instructions will be sent.</p>
      {error && <div className="mt-5"><ErrorMessage>{error}</ErrorMessage></div>}
      {sent ? <p className="mt-5 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm leading-6 text-emerald-900" role="status">If an active account matches that address, recovery instructions will be sent. Check your inbox and spam folder.</p> : <form onSubmit={submit} className="mt-6 space-y-4">
        <div><label className="mb-1.5 block text-sm font-medium text-slate-700" htmlFor="recovery-email">Email</label><input id="recovery-email" type="email" autoComplete="email" required maxLength={254} value={email} onChange={(event) => setEmail(event.target.value)} className="field" /></div>
        <button className="btn-primary w-full justify-center" type="submit" disabled={busy}>{busy ? "Sending…" : "Send recovery instructions"}</button>
      </form>}
      <Link className="mt-5 inline-flex items-center gap-2 text-sm text-slate-500 hover:text-ink-700" to="/login"><ArrowLeft size={15} />Back to sign in</Link>
    </section>
  </main>;
}
