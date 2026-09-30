import { useState } from "react";
import { api } from "../api";

export default function AuthScreen({ onAuth }) {
  const [mode, setMode] = useState("login"); // "login" | "signup"
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const fn = mode === "login" ? api.login : api.signup;
      const { access_token, email: returnedEmail } = await fn(email.trim(), password);
      onAuth(access_token, returnedEmail);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="connect-bank">
      <h2>{mode === "login" ? "Sign in" : "Create an account"}</h2>
      <p className="hint">
        {mode === "login"
          ? "Sign in to see your linked bank, budgets, and chat history."
          : "Your linked bank, budgets, and chat history will be saved to this account."}
      </p>

      <form className="auth-form" onSubmit={submit}>
        <input
          type="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          disabled={busy}
          required
        />
        <input
          type="password"
          placeholder={mode === "signup" ? "Password (min. 8 characters)" : "Password"}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          disabled={busy}
          required
          minLength={8}
        />
        <button type="submit" disabled={busy}>
          {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
        </button>
      </form>

      {error && <p className="error">Error: {error}</p>}

      <p className="hint" style={{ marginTop: 18 }}>
        {mode === "login" ? "No account yet? " : "Already have an account? "}
        <button
          type="button"
          className="ghost-button"
          onClick={() => {
            setMode(mode === "login" ? "signup" : "login");
            setError(null);
          }}
        >
          {mode === "login" ? "Create one" : "Sign in instead"}
        </button>
      </p>
    </div>
  );
}