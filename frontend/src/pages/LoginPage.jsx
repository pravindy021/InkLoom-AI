import { useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { ShieldCheck } from "lucide-react";
import { useAuth } from "../contexts/AuthContext";
import { ErrorMessage } from "../components/common/UI";
import { api } from "../services/api";
import { Link } from "react-router-dom";

export default function LoginPage() {
  const { user, signIn, authError } = useAuth();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [bootstrapConfigured, setBootstrapConfigured] = useState(null);
  const [recoveryEnabled, setRecoveryEnabled] = useState(false);

  useEffect(() => {
    let active = true;
    api.health()
      .then((health) => {
        if (active) setBootstrapConfigured(Boolean(health.bootstrap_admin_configured));
        if (active) setRecoveryEnabled(Boolean(health.password_recovery_enabled));
      })
      .catch(() => {
        if (active) {
          setBootstrapConfigured(null);
          setRecoveryEnabled(false);
        }
      });
    return () => { active = false; };
  }, []);

  if (user) return <Navigate to={user.must_change_password ? "/change-password" : location.state?.from?.pathname || "/"} replace />;

  const submit = async (event) => {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await signIn({ email, password });
    } catch (err) {
      setError(err.message || "Sign in failed.");
    } finally {
      setSubmitting(false);
    }
  };

  return <main className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-12">
    <section className="card w-full max-w-md p-6 sm:p-8">
      <div className="mb-7 flex items-center gap-3">
        <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-ink-900 text-white"><ShieldCheck size={22} /></span>
        <div><p className="text-lg font-bold text-ink-900">InkLoom AI</p><p className="text-xs text-slate-500">Secure workspace sign in</p></div>
      </div>
      <h1 className="text-xl font-bold text-ink-900">Welcome back</h1>
      <p className="mt-1 text-sm leading-6 text-slate-500">Sign in using the account invited by your workspace administrator.</p>
      {bootstrapConfigured === false && <div className="mt-5 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm leading-5 text-amber-900" role="status"><strong>Workspace administrator is not configured.</strong><span className="mt-1 block">Set BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD in backend/.env, protect the file, then restart the API. Bootstrap creates the first admin only when the database has no users.</span></div>}
      {(error || authError) && <div className="mt-5"><ErrorMessage>{error || authError}</ErrorMessage></div>}
      <form onSubmit={submit} className="mt-6 space-y-4">
        <div><label className="mb-1.5 block text-sm font-medium text-slate-700" htmlFor="login-email">Email</label><input id="login-email" type="email" autoComplete="username" required maxLength={254} value={email} onChange={(event) => setEmail(event.target.value)} className="field" /></div>
        <div><label className="mb-1.5 block text-sm font-medium text-slate-700" htmlFor="login-password">Password</label><input id="login-password" type="password" autoComplete="current-password" required maxLength={128} value={password} onChange={(event) => setPassword(event.target.value)} className="field" /></div>
        <button className="btn-primary w-full justify-center" type="submit" disabled={submitting}>{submitting ? "Signing in…" : "Sign in"}</button>
      </form>
      {recoveryEnabled && <p className="mt-4 text-center text-sm"><Link className="font-medium text-ink-700 underline" to="/forgot-password">Forgot your password?</Link></p>}
      <p className="mt-5 text-xs leading-5 text-slate-400">Accounts are invitation-only. Contact your workspace administrator if you need access.</p>
    </section>
  </main>;
}
