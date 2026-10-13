import { useEffect, useState } from "react";
import { api, getAuthToken, setAuthToken, setUnauthorizedHandler } from "./api";
import AuthScreen from "./components/AuthScreen.jsx";
import ConnectBank from "./components/ConnectBank.jsx";
import AlertsBanner from "./components/AlertsBanner.jsx";
import TransactionList from "./components/TransactionList.jsx";
import SpendingCharts from "./components/SpendingCharts.jsx";
import BudgetPanel from "./components/BudgetPanel.jsx";
import Chat from "./components/Chat.jsx";
import MonthPicker, { useMonthRange } from "./components/MonthPicker.jsx";

const EMAIL_KEY = "finance_agent_email";

export default function App() {
  const monthRange = useMonthRange();
  const [budgetRefreshToken, setBudgetRefreshToken] = useState(0);
  const [authed, setAuthed] = useState(!!getAuthToken());
  const [email, setEmail] = useState(localStorage.getItem(EMAIL_KEY) || "");
  const [linked, setLinked] = useState(false);
  const [isDemo, setIsDemo] = useState(false);
  const [checkingLink, setCheckingLink] = useState(true);

  // If the backend ever rejects our token (expired, server restarted with a
  // new JWT_SECRET, etc.), drop back to the login screen instead of the
  // dashboard silently failing on every request.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setAuthed(false);
      setLinked(false);
    });
  }, []);

  // Once authenticated, check whether this account already has a linked
  // bank (persists across refreshes now, unlike before auth existed).
  useEffect(() => {
    if (!authed) {
      setCheckingLink(false);
      return;
    }
    setCheckingLink(true);
    api
      .getLinkStatus()
      .then((res) => {
        setLinked(!!res.linked);
        setIsDemo(!!res.is_demo);
      })
      .catch(() => setLinked(false))
      .finally(() => setCheckingLink(false));
  }, [authed]);

  const handleAuth = (token, userEmail) => {
    setAuthToken(token);
    localStorage.setItem(EMAIL_KEY, userEmail);
    setEmail(userEmail);
    setAuthed(true);
  };

  const handleLogout = () => {
    setAuthToken(null);
    localStorage.removeItem(EMAIL_KEY);
    setAuthed(false);
    setLinked(false);
    setIsDemo(false);
  };

  if (!authed) {
    return (
      <div className="app">
        <div className="masthead">
          <h1>Finance Agent</h1>
          <span className="tag">sign in</span>
        </div>
        <AuthScreen onAuth={handleAuth} />
      </div>
    );
  }

  return (
    <div className="app">
      <div className="masthead">
        <h1>Finance Agent</h1>
        <div className="masthead-right">
          <span className="tag">
            {isDemo ? "demo account" : linked ? "sandbox · connected" : "sandbox mode"}
            {!isDemo && ` · ${email}`}
          </span>
          <button className="ghost-button" onClick={handleLogout}>
            log out
          </button>
        </div>
      </div>

      {checkingLink ? (
        <p className="hint">Loading…</p>
      ) : !linked ? (
        <ConnectBank onLinked={() => setLinked(true)} />
      ) : (
        <main className="dashboard">
          {isDemo && (
            <p className="demo-banner">
              You're exploring a demo account with sample data (kept for 24 hours). Chat is limited
              to a few messages. <button className="ghost-button" onClick={handleLogout}>Create a real account</button> to
              connect a Plaid sandbox bank.
            </p>
          )}
          <AlertsBanner />
          <TransactionList />
          <MonthPicker range={monthRange} />
          <SpendingCharts monthRange={monthRange} />
          <BudgetPanel monthRange={monthRange} refreshToken={budgetRefreshToken} />
          <Chat onBudgetChanged={() => setBudgetRefreshToken((t) => t + 1)} />
        </main>
      )}
    </div>
  );
}
