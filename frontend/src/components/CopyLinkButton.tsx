// Copies the share link for a saved chart (https://site/c/<id>) to the clipboard.

import { useState } from "react";
import { buttonGhost } from "./ui";

export function CopyLinkButton({ chartId }: { chartId: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(`${location.origin}/c/${chartId}`);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access can be blocked (e.g. on plain http). The link is still in the address bar of /c/<id>.
    }
  }

  return (
    <button className={buttonGhost} onClick={copy}>
      {copied ? "Copied" : "Copy link"}
    </button>
  );
}
