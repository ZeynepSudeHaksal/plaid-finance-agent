import { useCallback, useEffect, useState } from "react";
import { usePlaidLink } from "react-plaid-link";
import { api } from "../api";

/**
 * Handles the full Plaid Link flow:
 *   1. fetch a link_token from the backend
 *   2. open Plaid Link with it
 *   3. on success, exchange the public_token via the backend
 *   4. trigger a transaction sync
 *
 * Calls onLinked() once a bank is connected and transactions are synced,
 * so the parent can switch to the chat view.
 */
export default function ConnectBank({ onLinked }) {
  const [linkToken, setLinkToken] = useState(null);
  const [status, setStatus] = useState("idle"); // idle | loading | linking | syncing | error
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .getLinkToken()
      .then(({ link_token }) => setLinkToken(link_token))
      .catch((e) => {
        setError(e.message);
        setStatus("error");
      });
  }, []);

  const onSuccess = useCallback(
    async (public_token, metadata) => {
      setStatus("linking");
      try {
        await api.exchangeToken(public_token, metadata?.institution?.name ?? null);
        setStatus("syncing");
        const result = await api.syncTransactions();
        onLinked(result);
      } catch (e) {
        setError(e.message);
        setStatus("error");
      }
    },
    [onLinked]
  );

  const { open, ready } = usePlaidLink({
    token: linkToken,
    onSuccess,
  });

  return (
    <div className="connect-bank">
      <h2>Connect a bank account</h2>
      <p className="hint">
        Sandbox mode — pick any institution, then log in with{" "}
        <code>user_good</code> / <code>pass_good</code>.
      </p>

      <button
        onClick={() => {
          setStatus("loading");
          open();
        }}
        disabled={!ready || status === "linking" || status === "syncing"}
      >
        {status === "linking" && "Linking..."}
        {status === "syncing" && "Syncing transactions..."}
        {status === "idle" || status === "loading" ? "Connect a bank" : null}
      </button>

      {error && <p className="error">Error: {error}</p>}
    </div>
  );
}
