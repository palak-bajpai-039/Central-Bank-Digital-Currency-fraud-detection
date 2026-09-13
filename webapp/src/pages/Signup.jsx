import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { Shield, Copy, Check } from "lucide-react";
import { api, setToken } from "../api";

export default function Signup() {
  const [orgName, setOrgName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [revealedKey, setRevealedKey] = useState(null);
  const [copied, setCopied] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }
    setLoading(true);
    try {
      const { api_key } = await api.signup(orgName, email, password);
      setRevealedKey(api_key);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleContinue() {
    const { access_token } = await api.login(email, password);
    setToken(access_token);
    navigate("/dashboard");
  }

  function copyKey() {
    navigator.clipboard.writeText(revealedKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  if (revealedKey) {
    return (
      <div className="auth-shell">
        <div className="auth-card">
          <h1>Save your API key</h1>
          <p className="subtitle">
            This is shown <strong>once</strong> — the same way Stripe or AWS handle keys.
            It's already hashed server-side; even we can't retrieve it again after this.
          </p>
          <div className="key-plain-box">{revealedKey}</div>
          <button className="btn-secondary" onClick={copyKey} style={{ width: "100%", marginBottom: 10, display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
            {copied ? <Check size={16} /> : <Copy size={16} />} {copied ? "Copied" : "Copy key"}
          </button>
          <button className="btn-primary" onClick={handleContinue} style={{ width: "100%" }}>
            Continue to dashboard
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20 }}>
          <Shield size={22} color="var(--teal)" />
          <span style={{ fontWeight: 700 }}>CBDC Fraud Detection</span>
        </div>
        <h1>Create an account</h1>
        <p className="subtitle">Sign up your organization and get a real-time fraud-check API</p>
        {error && <div className="error">{error}</div>}
        <form onSubmit={handleSubmit}>
          <div>
            <label className="label">Organization name</label>
            <input required value={orgName} onChange={(e) => setOrgName(e.target.value)} placeholder="Acme Payments" />
          </div>
          <div>
            <label className="label">Email</label>
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" />
          </div>
          <div>
            <label className="label">Password</label>
            <input type="password" required value={password} onChange={(e) => setPassword(e.target.value)} placeholder="At least 8 characters" />
          </div>
          <button type="submit" className="btn-primary" disabled={loading}>
            {loading ? "Creating account…" : "Sign up"}
          </button>
        </form>
        <p className="footer-link">
          Already have an account? <Link to="/login">Log in</Link>
        </p>
      </div>
    </div>
  );
}
