import { useEffect, useState } from "react";
import { Plus, Trash2, Copy, Check } from "lucide-react";
import { api } from "../api";
import Layout from "../components/Layout";

export default function ApiKeys() {
  const [me, setMe] = useState(null);
  const [keys, setKeys] = useState([]);
  const [newKey, setNewKey] = useState(null);
  const [copied, setCopied] = useState(false);
  const [loading, setLoading] = useState(false);

  async function refresh() {
    const [meData, keysData] = await Promise.all([api.me(), api.listKeys()]);
    setMe(meData);
    setKeys(keysData);
  }

  useEffect(() => { refresh(); }, []);

  async function handleCreate() {
    setLoading(true);
    try {
      const result = await api.createKey();
      setNewKey(result.api_key);
      refresh();
    } finally {
      setLoading(false);
    }
  }

  async function handleRevoke(id) {
    if (!confirm("Revoke this key? Anything using it will stop working immediately.")) return;
    await api.revokeKey(id);
    refresh();
  }

  function copyKey() {
    navigator.clipboard.writeText(newKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <Layout me={me}>
      <h2 style={{ marginTop: 0 }}>API Keys</h2>
      <p style={{ color: "var(--muted)", fontSize: 13, marginTop: -10 }}>
        Use these to call the fraud-check API from your own backend (server-to-server).
        The dashboard itself uses your login session, not a key.
      </p>

      {newKey && (
        <div className="card" style={{ marginBottom: 18, borderColor: "var(--teal)" }}>
          <p style={{ margin: "0 0 8px", fontSize: 13, fontWeight: 600 }}>
            New key created — copy it now, it won't be shown again
          </p>
          <div className="key-plain-box">{newKey}</div>
          <button className="btn-secondary" onClick={copyKey} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {copied ? <Check size={15} /> : <Copy size={15} />} {copied ? "Copied" : "Copy"}
          </button>
        </div>
      )}

      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
          <h3 style={{ margin: 0, fontSize: 15 }}>Your keys</h3>
          <button className="btn-primary" onClick={handleCreate} disabled={loading} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <Plus size={15} /> New key
          </button>
        </div>
        {keys.length === 0 ? (
          <p className="empty-state">No keys yet.</p>
        ) : (
          keys.map((k) => (
            <div className="key-row" key={k.id}>
              <div>
                <div style={{ fontFamily: "monospace" }}>{k.key_prefix}••••••••••••••••</div>
                <div className="txn-meta">
                  Created {new Date(k.created_at).toLocaleDateString()}
                  {k.last_used_at && ` · last used ${new Date(k.last_used_at).toLocaleDateString()}`}
                  {k.revoked && " · revoked"}
                </div>
              </div>
              {!k.revoked && (
                <button className="btn-danger" onClick={() => handleRevoke(k.id)} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <Trash2 size={14} /> Revoke
                </button>
              )}
            </div>
          ))
        )}
      </div>
    </Layout>
  );
}
