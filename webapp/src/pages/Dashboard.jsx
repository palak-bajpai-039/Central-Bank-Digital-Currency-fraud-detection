import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Wallet, Send, Bell } from "lucide-react";
import { api, wsUrl } from "../api";
import Layout from "../components/Layout";

const TXN_TYPES = ["P2P_TRANSFER", "P2M_PAYMENT", "COLLECT_REQUEST", "QR_SCAN", "BILL_PAYMENT", "RECHARGE"];

export default function Dashboard() {
  const [me, setMe] = useState(null);
  const [stats, setStats] = useState({ total_transactions: 0, held_for_review: 0, avg_risk_score: 0 });
  const [feed, setFeed] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [connected, setConnected] = useState(false);
  const [receiver, setReceiver] = useState("");
  const [amount, setAmount] = useState(500);
  const [txnType, setTxnType] = useState("P2P_TRANSFER");
  const [sendResult, setSendResult] = useState(null);
  const [sending, setSending] = useState(false);
  const wsRef = useRef(null);

  async function refreshAll() {
    const [meData, statsData, txns, alertsData] = await Promise.all([
      api.me(), api.stats(), api.listTransactions(), api.listAlerts(),
    ]);
    setMe(meData);
    setStats(statsData);
    setFeed(txns);
    setAlerts(alertsData);
  }

  useEffect(() => {
    refreshAll();

    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission();
    }

    function connect() {
      const ws = new WebSocket(wsUrl());
      wsRef.current = ws;
      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        setTimeout(connect, 2000);
      };
      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.event !== "transaction") return;
        // Only react to OUR org's transactions — the WS broadcasts platform-wide
        // (useful for an ops/admin view), but a customer dashboard should only
        // show its own activity.
        if (me && msg.data.org_id !== me.org_id) return;
        setFeed((prev) => [msg.data, ...prev].slice(0, 50));
        if (msg.data.status === "held_for_review") {
          setAlerts((prev) => [msg.data, ...prev].slice(0, 50));
          notify(msg.data);
        }
        api.stats().then(setStats);
        api.me().then(setMe);
      };
    }
    connect();
    return () => wsRef.current?.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me?.org_id]);

  function notify(txn) {
    if (!("Notification" in window) || Notification.permission !== "granted") return;
    const n = new Notification("⚠ Transaction flagged for review", {
      body: `${txn.sender_vpa} → ${txn.receiver_vpa} · ₹${Number(txn.amount).toLocaleString("en-IN")} · risk ${(txn.risk_score * 100).toFixed(0)}%`,
    });
    n.onclick = () => window.focus();
  }

  async function handleSend(e) {
    e.preventDefault();
    setSending(true);
    setSendResult(null);
    try {
      const result = await api.sendTransaction({
        sender_vpa: me.wallet.vpa,
        receiver_vpa: receiver,
        amount: parseFloat(amount),
        type: txnType,
      });
      setSendResult(result);
      refreshAll();
    } catch (err) {
      setSendResult({ status: "error", reasons: [err.message] });
    } finally {
      setSending(false);
    }
  }

  if (!me) return <Layout><p style={{ color: "var(--muted)" }}>Loading…</p></Layout>;

  return (
    <Layout me={me}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <h2 style={{ margin: 0 }}>Dashboard</h2>
        <div style={{ fontSize: 13, color: "var(--muted)" }}>
          <span className={`status-dot ${connected ? "connected" : "disconnected"}`}></span>
          {connected ? "Live" : "Connecting…"}
        </div>
      </div>

      <div className="grid-metrics">
        <div className="card metric-card">
          <div className="metric-label"><Wallet size={13} style={{ verticalAlign: "-2px", marginRight: 5 }} />Wallet balance</div>
          <div className="metric-value">₹{Number(me.wallet.balance).toLocaleString("en-IN")}</div>
        </div>
        <div className="card metric-card">
          <div className="metric-label">Total transactions</div>
          <div className="metric-value">{stats.total_transactions}</div>
        </div>
        <div className="card metric-card">
          <div className="metric-label">Held for review</div>
          <div className="metric-value" style={{ color: "var(--red)" }}>{stats.held_for_review}</div>
        </div>
        <div className="card metric-card">
          <div className="metric-label">Avg risk score</div>
          <div className="metric-value">{Math.round(stats.avg_risk_score * 100)}%</div>
        </div>
      </div>

      <div className="layout-2col">
        <div>
          <div className="card" style={{ marginBottom: 18 }}>
            <h3 style={{ marginTop: 0, fontSize: 15 }}>Live transaction feed</h3>
            {feed.length === 0 ? (
              <p className="empty-state">No transactions yet — send one to see it scored in real time.</p>
            ) : (
              feed.slice(0, 12).map((t) => (
                <div className="txn-row" key={t.id}>
                  <div>
                    <div>{t.sender_vpa} → {t.receiver_vpa}</div>
                    <div className="txn-meta">₹{Number(t.amount).toLocaleString("en-IN")} · {t.type} · risk {(t.risk_score * 100).toFixed(0)}%</div>
                  </div>
                  <span className={`badge ${t.status}`}>{t.status === "approved" ? "Approved" : "Held"}</span>
                </div>
              ))
            )}
          </div>
        </div>

        <div>
          <div className="card" style={{ marginBottom: 18 }}>
            <h3 style={{ marginTop: 0, fontSize: 15, display: "flex", alignItems: "center", gap: 8 }}>
              <Send size={15} /> Send money
            </h3>
            <p style={{ fontSize: 12, color: "var(--muted)", marginTop: -8 }}>From your wallet: {me.wallet.vpa}</p>
            <form onSubmit={handleSend} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div>
                <label className="label">To (receiver VPA)</label>
                <input required value={receiver} onChange={(e) => setReceiver(e.target.value)} placeholder="anyone@upi" />
              </div>
              <div>
                <label className="label">Amount (₹)</label>
                <input type="number" min="1" required value={amount} onChange={(e) => setAmount(e.target.value)} />
              </div>
              <div>
                <label className="label">Transaction type</label>
                <select value={txnType} onChange={(e) => setTxnType(e.target.value)}>
                  {TXN_TYPES.map((t) => <option key={t}>{t}</option>)}
                </select>
              </div>
              <button type="submit" className="btn-primary" disabled={sending}>
                {sending ? "Scoring…" : "Send"}
              </button>
            </form>
            {sendResult && (
              <div
                style={{
                  marginTop: 12, padding: 12, borderRadius: 8, fontSize: 13,
                  background: sendResult.status === "approved" ? "var(--green-bg)" : "var(--red-bg)",
                  color: sendResult.status === "approved" ? "var(--green)" : "var(--red)",
                }}
              >
                {sendResult.status === "approved"
                  ? `✓ Approved (risk ${(sendResult.risk_score * 100).toFixed(0)}%)`
                  : `⚠ ${sendResult.status === "error" ? "Error" : "Held for review"} — ${sendResult.reasons?.join(", ")}`}
              </div>
            )}
          </div>

          <div className="card">
            <h3 style={{ marginTop: 0, fontSize: 15, display: "flex", alignItems: "center", gap: 8 }}>
              <Bell size={15} /> Alerts
            </h3>
            {alerts.length === 0 ? (
              <p className="empty-state">No alerts yet.</p>
            ) : (
              alerts.slice(0, 8).map((a) => (
                <div className="txn-row" key={a.id || a.transaction_id}>
                  <div>
                    <div>{a.sender_vpa} → {a.receiver_vpa}</div>
                    <div className="txn-meta"><AlertTriangle size={11} style={{ verticalAlign: "-1px" }} /> {a.reasons}</div>
                  </div>
                  <span className="badge held_for_review">{(a.risk_score * 100).toFixed(0)}%</span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </Layout>
  );
}
