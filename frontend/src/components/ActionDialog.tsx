import { useEffect, useId, useRef, useState, type FormEvent } from "react";

type Props = {
  title: string;
  description: string;
  /** Label of the button that does the action, e.g. "Remove from Hop". */
  confirmLabel: string;
  /** Red styling for actions that are hard or impossible to undo. */
  danger?: boolean;
  /** When set, the admin must type this exact text (e.g. the page URL). */
  confirmText?: string;
  /** Gets the reason and, with confirmText, what the admin typed. */
  onConfirm: (reason: string, typed: string) => Promise<void>;
  onClose: () => void;
};

/**
 * Asks for a reason before an admin action, in a native <dialog>: it traps
 * focus, closes with Escape, and is announced as a dialog by screen readers.
 */
export default function ActionDialog({
  title,
  description,
  confirmLabel,
  danger = false,
  confirmText,
  onConfirm,
  onClose,
}: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [reason, setReason] = useState("");
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const titleId = useId();

  useEffect(() => {
    dialog.current?.showModal();
  }, []);

  const ready =
    reason.trim().length > 0 &&
    (confirmText === undefined || typed.trim() === confirmText);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!ready) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onConfirm(reason.trim(), typed.trim());
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setBusy(false);
    }
  }

  return (
    <dialog
      ref={dialog}
      className="action-dialog card"
      aria-labelledby={titleId}
      onClose={onClose}
    >
      <form onSubmit={handleSubmit} className="form">
        <h2 id={titleId}>{title}</h2>
        <p className="muted">{description}</p>
        <label>
          Reason (saved in the page's history)
          <textarea
            value={reason}
            maxLength={300}
            rows={3}
            required
            onChange={(e) => setReason(e.target.value)}
          />
        </label>
        {confirmText !== undefined && (
          <label>
            Type the page's URL to confirm
            <input
              type="text"
              value={typed}
              autoComplete="off"
              spellCheck={false}
              onChange={(e) => setTyped(e.target.value)}
            />
            <span className="hint">{confirmText}</span>
          </label>
        )}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="dialog-buttons">
          <button type="button" className="button secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            className={danger ? "danger" : undefined}
            disabled={!ready || busy}
          >
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </form>
    </dialog>
  );
}
