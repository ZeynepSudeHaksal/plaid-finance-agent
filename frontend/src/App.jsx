import { useState } from "react";
import ConnectBank from "./components/ConnectBank.jsx";
import TransactionList from "./components/TransactionList.jsx";
import Chat from "./components/Chat.jsx";

export default function App() {
  // Simple local flag — no persistence yet. Refreshing the page will
  // ask you to reconnect, even though the backend still has the linked
  // item. Good enough for now; revisit once there's a real user/session.
  const [linked, setLinked] = useState(false);

  return (
    <div className="app">
      <header>
        <h1>Finance Agent</h1>
      </header>

      {!linked ? (
        <ConnectBank onLinked={() => setLinked(true)} />
      ) : (
        <main className="dashboard">
          <TransactionList />
          <Chat />
        </main>
      )}
    </div>
  );
}
