"use strict";

// Optional enhancement: content, links and navigation also work without JavaScript.
for (const pre of document.querySelectorAll(".doc-body pre")) {
  const code = pre.querySelector("code");
  if (!code || !navigator.clipboard || !window.isSecureContext) continue;
  const button = document.createElement("button");
  button.className = "copy-button";
  button.type = "button";
  button.textContent = "Copy";
  button.setAttribute("aria-label", "Copy code example");
  button.addEventListener("click", async () => {
    const status = document.getElementById("copy-status");
    try {
      await navigator.clipboard.writeText(code.textContent);
      button.textContent = "Copied";
      status.textContent = "Code example copied. Replace example paths and names before running it.";
    } catch {
      status.textContent = "Copy unavailable. Select the example text to copy it.";
    }
  });
  pre.append(button);
}
