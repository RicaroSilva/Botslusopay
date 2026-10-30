import { useState, type FormEvent } from "react";
import { useAuth } from "../auth";
import { ErrorBox } from "../components/ui";

export function Login() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={submit}>
        <div className="brand">
          <span className="brand-mark">LP</span>
          <div>
            <strong>LUSOPAY</strong>
            <small>Bot Manager</small>
          </div>
        </div>
        <label>
          Utilizador
          <input autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
        </label>
        <label>
          Password
          <input type="password" autoComplete="current-password" value={password}
            onChange={(e) => setPassword(e.target.value)} required />
        </label>
        <ErrorBox error={error} />
        <button className="btn btn-primary" disabled={busy}>{busy ? "A entrar…" : "Entrar"}</button>
        <p className="muted small">Aplicação interna. Todas as ações são registadas para auditoria.</p>
      </form>
    </div>
  );
}
