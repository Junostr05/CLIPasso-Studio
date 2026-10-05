// CLIPasso Studio – signing in with the PIN (when the phone no longer has the cookie of the QR code).
"use strict";

const CFG = JSON.parse(document.getElementById("cfg").textContent);
const T = CFG.texts || {};
const $ = (id) => document.getElementById(id);
for (const node of document.querySelectorAll("[data-t]")) node.textContent = T[node.dataset.t] || node.dataset.t;
$("pin").placeholder = "••••••";
$("pin").focus();

$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const pin = $("pin").value.replace(/\D/g, "");
  if (pin.length !== 6) { $("msg").textContent = T.login_six; return; }
  $("go").disabled = true;
  try {
    const r = await fetch("/login", {method: "POST", headers: {"Content-Type": "application/json"},
                                     body: JSON.stringify({pin})});
    const a = await r.json().catch(() => ({}));
    if (a.ok) { location.replace("/"); return; }
    $("pin").value = "";
    $("msg").textContent = a.wait ? (T.login_wait || "").replace("{s}", a.wait) : T.login_wrong;
  } catch (err) {
    $("msg").textContent = T.offline;
  }
  $("go").disabled = false;
  $("pin").focus();
});
